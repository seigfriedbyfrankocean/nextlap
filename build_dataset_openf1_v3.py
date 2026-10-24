"""
Build the next-lap dataset from OpenF1.

Usage (inside the activated .venv, in the project folder):
    python build_dataset_openf1_v3.py                 build the dataset
    python build_dataset_openf1_v3.py inspect 11299   show how one session's race control messages are classified
    python build_dataset_openf1_v3.py compare         compare the new dataset with the current laps_sample.csv

Outputs go to *_v3 files and a new cache folder, so nothing existing is overwritten.
"""
import os
import sys
import time

import numpy as np
import pandas as pd
import requests

BASE = "https://api.openf1.org/v1"
PAUSE = 0.7
PARTS_DIR = "race_parts_openf1_v3"        # new cache, so old cached races can never bypass the new logic
OUTPUT_DATA = "laps_sample_v3.csv"
OUTPUT_LOG = "removal_log_v3.csv"
OUTPUT_WINDOWS = "race_control_windows_v3.csv"
OUTPUT_EXCLUDED = "excluded_races_v3.csv"
OUTPUT_SKIPPED = "skipped_races_v3.csv"
OLD_DATA = "laps_sample.csv"

START_YEAR = 2023
END_YEAR = pd.Timestamp.today().year
MAX_FAILURES_IN_A_ROW = 3

# ---- Thresholds (all kept from the previous version unless marked NEW) ----
SLOW_FACTOR = 1.10          # a lap is "slow" if it is more than 10% above its own stint median
SC_MAX_MINUTES = 30         # cap for a safety car / VSC window with no observed end marker
RED_MAX_MINUTES = 60        # cap for a red flag window with no observed end marker
MIN_COVERAGE = 0.75         # raw laps / (drivers x race length); below this the download is incomplete
MAX_WET_LAP_SHARE = 0.10    # of laps with KNOWN rainfall
MAX_WET_TYRE_SHARE = 0.02   # of laps with a known compound
MIN_ROWS = 300              # races with fewer surviving rows are excluded
MIN_WEATHER_COVERAGE = 0.50 # NEW: share of laps that need a weather reading, else dry/wet cannot be judged
WEATHER_TOLERANCE = pd.Timedelta(minutes=10)  # NEW: a lap never uses a weather reading older than this

COLUMNS = [
    "Driver", "Team", "Year", "Round", "Circuit",
    "Compound", "TyreLife", "FreshTyre", "Stint",
    "LapNumber", "TrackTemp", "AirTemp", "Rainfall",
    "InSafetyCar", "LapSeconds", "NextLapNumber",
    "NextLapSeconds"
]

WINDOW_COLUMNS = [
    "Year", "Round", "Circuit", "SessionKey",
    "kind", "start", "end", "minutes", "how_closed"
]

# Fields copied from a lap's NEXT lap (joined on driver and exact lap number + 1).
NEXT_FIELDS = {
    "lap_duration": "NextLapSeconds",
    "is_pit_out_lap": "NextIsPitOut",
    "is_in_lap": "NextIsInLap",
    "InSafetyCar": "NextInSafetyCar",
    "StintMedian": "NextStintMedian",
}


# --------------------------------------------------------------------------
# Small parsing helpers
# --------------------------------------------------------------------------
TRUE_STRINGS = {"true", "t", "yes", "y", "1"}
FALSE_STRINGS = {"false", "f", "no", "n", "0"}
EMPTY_STRINGS = {"", "none", "nan", "null", "nat"}


def parse_bool(series, default=False):
    """
    Explicit boolean parser. astype(bool) is unsafe because the string "False" is truthy.
    Real booleans, numbers and common strings are handled; anything unrecognised raises.
    """
    def convert(v):
        if isinstance(v, (bool, np.bool_)):
            return bool(v)
        if v is None or v is pd.NA or v is pd.NaT:
            return default
        if isinstance(v, (int, float, np.integer, np.floating)):
            return default if pd.isna(v) else bool(v)
        s = str(v).strip().lower()
        if s in TRUE_STRINGS:
            return True
        if s in FALSE_STRINGS:
            return False
        if s in EMPTY_STRINGS:
            return default
        raise ValueError(f"Unrecognised boolean value: {v!r}")

    return series.map(convert).astype(bool)


def parse_rain(series):
    """Rainfall as a float. Unknown stays NaN (it is never turned into 0)."""
    def convert(v):
        if v is None or v is pd.NA:
            return np.nan
        if isinstance(v, (bool, np.bool_)):
            return float(v)
        if isinstance(v, (int, float, np.integer, np.floating)):
            return np.nan if pd.isna(v) else float(v)
        s = str(v).strip().lower()
        if s in {"true", "yes"}:
            return 1.0
        if s in {"false", "no"}:
            return 0.0
        try:
            return float(s)
        except ValueError:
            return np.nan

    return series.map(convert).astype(float)


def to_utc(series):
    """UTC timestamps with a fixed nanosecond resolution, so merge_asof never sees mismatched dtypes."""
    out = pd.to_datetime(series, utc=True, format="ISO8601", errors="coerce")
    return out.astype("datetime64[ns, UTC]")


# --------------------------------------------------------------------------
# API access
# --------------------------------------------------------------------------
def get(endpoint, **params):
    """
    Fetch one OpenF1 endpoint.
    404 means 'no results' and returns an empty frame. 429 and 5xx errors retry.
    Every other HTTP error is raised so it cannot be swallowed silently.
    """
    last_problem = ""

    for attempt in range(6):
        try:
            r = requests.get(f"{BASE}/{endpoint}", params=params, timeout=60)
        except requests.RequestException as e:
            last_problem = f"network error: {e}"
            time.sleep(5 * (attempt + 1))
            continue

        if r.status_code == 404:
            time.sleep(PAUSE)
            return pd.DataFrame()

        if r.status_code == 429 or r.status_code >= 500:
            last_problem = f"HTTP {r.status_code}"
            wait = 10 * (attempt + 1)
            retry_after = r.headers.get("Retry-After", "")
            if retry_after.isdigit():
                wait = max(wait, int(retry_after))
            time.sleep(wait)
            continue

        r.raise_for_status()
        time.sleep(PAUSE)

        data = r.json()
        if isinstance(data, dict):
            raise RuntimeError(f"Unexpected response from {endpoint}: {data}")
        return pd.DataFrame(data)

    raise RuntimeError(
        f"Request failed after retries ({last_problem}): {endpoint} {params}"
    )


def list_races():
    """Race sessions whose scheduled end time has passed, numbered per season by date."""
    now = pd.Timestamp.now(tz="UTC")
    races = []

    for year in range(START_YEAR, END_YEAR + 1):
        df = get("sessions", year=year, session_name="Race")

        if df.empty:
            continue

        df["date_end"] = to_utc(df["date_end"])
        df["date_start"] = to_utc(df["date_start"])
        df = df[df["date_end"] < now]

        if "is_cancelled" in df.columns:
            df = df[~parse_bool(df["is_cancelled"])]

        df = df.drop_duplicates("session_key")
        df = df.sort_values("date_start").reset_index(drop=True)

        for rnd, row in enumerate(df.itertuples(), 1):
            races.append((year, rnd, row.circuit_short_name, int(row.session_key)))

    return races


# --------------------------------------------------------------------------
# Race control: safety car, VSC and red flag windows
# --------------------------------------------------------------------------
# Messages that look related but are reports about penalties or incidents.
NOISE_WORDS = (
    "INFRINGEMENT", "PENALTY", "INVESTIGATION", "NOTED", "REVIEW", "DELETED",
)
RESTART_MARKERS = (
    "GREEN LIGHT", "PIT EXIT OPEN", "SESSION RESUMED", "RACE RESUMED",
)


def classify_event(message, flag=""):
    """
    Map one race control message to an event name, or "" if it does not matter.
    Announcements such as 'RACE WILL RESUME AT 17:12' deliberately map to "":
    they say when the race will restart, not that it has.
    """
    msg = str(message).upper().strip()
    flag = str(flag).upper().strip()

    if msg in ("", "NAN", "NONE"):
        return ""
    if any(w in msg for w in NOISE_WORDS):
        return ""

    if "CHEQUERED" in msg:
        return "CHEQUERED"

    if "VIRTUAL SAFETY CAR" in msg or "VSC" in msg:
        if "DEPLOYED" in msg:
            return "VSC_DEPLOY"
        if "ENDING" in msg or "ENDED" in msg:
            return "VSC_END"
        return ""

    if "SAFETY CAR" in msg:
        if "DEPLOYED" in msg:
            return "SC_DEPLOY"
        if "IN THIS LAP" in msg or "WITHDRAWN" in msg:
            return "SC_END"
        if "LIGHTS ON" in msg:
            return "SC_LIGHTS"
        return ""

    if (
        msg.startswith("RED FLAG")
        or msg in ("RACE SUSPENDED", "SESSION SUSPENDED")
        or (flag == "RED" and "RED FLAG" in msg)
    ):
        return "RED"

    if any(w in msg for w in RESTART_MARKERS):
        return "RESTART"

    return ""


def _cap(kind):
    minutes = RED_MAX_MINUTES if kind == "RED" else SC_MAX_MINUTES
    return pd.Timedelta(minutes=minutes)


def build_windows(control, race_end):
    """
    Turn race control messages into neutralised periods (SC, VSC, RED).

    Rules:
    - A window closes on an observed end marker, a transition, the chequered flag,
      or, if none is ever seen, a cap or the end of the race.
    - Windows closed by the cap or the race end are labelled so they can be audited.
    - A red flag becomes a safety car window on 'SAFETY CAR LIGHTS ON' or a new deployment.
    """
    if control.empty or "message" not in control.columns or "date" not in control.columns:
        return []

    rc = control.copy()
    rc["date"] = to_utc(rc["date"])
    rc = rc.dropna(subset=["date"]).sort_values("date")
    flags = rc["flag"] if "flag" in rc.columns else pd.Series("", index=rc.index)

    windows = []
    cur = None

    def close(end, how):
        nonlocal cur
        windows.append({
            "kind": cur["kind"], "start": cur["start"],
            "end": end, "how_closed": how,
        })
        cur = None

    for t, msg, flag in zip(rc["date"], rc["message"], flags):
        # Ignore race-control records timestamped after the last completed lap.
        # They can otherwise open a new window that the race_end fallback closes backward.
        if pd.notna(race_end) and t > race_end:
            break

        event = classify_event(msg, flag)

        # A window that has been open longer than its cap is closed at the cap.
        if cur is not None and t - cur["start"] > _cap(cur["kind"]):
            close(cur["start"] + _cap(cur["kind"]), "cap")

        if event in ("SC_DEPLOY", "VSC_DEPLOY", "SC_LIGHTS"):
            kind = "VSC" if event == "VSC_DEPLOY" else "SC"
            if cur is None:
                cur = {"kind": kind, "start": t}
            elif cur["kind"] == "RED":
                close(t, "transition_to_sc")
                cur = {"kind": kind, "start": t}
            elif cur["kind"] == "VSC" and kind == "SC":
                cur["kind"] = "SC"

        elif event == "RED":
            if cur is None:
                cur = {"kind": "RED", "start": t}
            elif cur["kind"] != "RED":
                close(t, "red_flag")
                cur = {"kind": "RED", "start": t}

        elif event == "SC_END":
            if cur is not None and cur["kind"] == "SC":
                close(t, "observed")

        elif event == "VSC_END":
            if cur is not None and cur["kind"] == "VSC":
                close(t, "observed")

        elif event == "RESTART":
            if cur is not None and cur["kind"] == "RED":
                close(t, "observed")

        elif event == "CHEQUERED":
            if cur is not None:
                close(t, "chequered")

    if cur is not None:
        capped_end = cur["start"] + _cap(cur["kind"])
        if pd.notna(race_end) and race_end < capped_end:
            close(race_end, "race_end")
        else:
            close(capped_end, "cap")

    return windows


# --------------------------------------------------------------------------
# One race
# --------------------------------------------------------------------------
def attach_next(df, fields):
    """
    Add each lap's NEXT lap values by joining on driver and exact lap number + 1.
    A missing lap gives NaN instead of silently pointing at a later lap, and
    NextLapNumber always holds the lap number the values really came from.
    """
    nxt = df[["driver_number", "lap_number"] + list(fields)].copy()
    nxt["NextLapNumber"] = nxt["lap_number"]
    nxt["lap_number"] = nxt["lap_number"] - 1
    nxt = nxt.rename(columns=fields)
    return df.merge(
        nxt, on=["driver_number", "lap_number"],
        how="left", validate="one_to_one"
    )


def excluded(log, reason, windows_df):
    log = dict(log)
    log["excluded"] = reason
    log["prediction_rows"] = 0
    return pd.DataFrame(columns=COLUMNS), log, windows_df


def get_clean_laps(year, rnd, circuit, key):
    raw = get("laps", session_key=key)
    if raw.empty:
        raise RuntimeError("No lap data")

    stints = get("stints", session_key=key)
    drivers = get("drivers", session_key=key)
    weather = get("weather", session_key=key)
    control = get("race_control", session_key=key)

    if stints.empty:
        raise RuntimeError("No tyre stint data")
    if drivers.empty:
        raise RuntimeError("No driver data")

    # ---- Raw laps ----
    needed = ["driver_number", "lap_number", "date_start",
              "lap_duration", "is_pit_out_lap"]
    absent = [c for c in needed if c not in raw.columns]
    if absent:
        raise RuntimeError(f"Lap data is missing columns: {absent}")

    laps = raw[needed].copy()
    laps = laps.dropna(subset=["driver_number", "lap_number"])
    laps["driver_number"] = laps["driver_number"].astype(int)
    laps["lap_number"] = laps["lap_number"].astype(int)
    laps["date_start"] = to_utc(laps["date_start"])
    laps["is_pit_out_lap"] = parse_bool(laps["is_pit_out_lap"])
    laps["lap_duration"] = pd.to_numeric(laps["lap_duration"], errors="coerce")

    before_dedupe = len(laps)
    laps = laps.drop_duplicates(["driver_number", "lap_number"], keep="first")
    dup_laps = before_dedupe - len(laps)

    laps = laps.sort_values(["driver_number", "lap_number"]).reset_index(drop=True)

    raw_laps = len(laps)
    coverage = raw_laps / max(laps["driver_number"].nunique() * laps["lap_number"].max(), 1)

    log = {
        "Year": year, "Round": rnd, "Circuit": circuit, "SessionKey": key,
        "raw_laps": raw_laps, "dup_laps": dup_laps,
        "coverage": round(float(coverage), 3), "excluded": "",
    }
    no_windows = pd.DataFrame(columns=WINDOW_COLUMNS)

    if coverage < MIN_COVERAGE:
        return excluded(log, "incomplete lap data", no_windows)

    # An in-lap is the lap directly before a pit-out lap (consecutive lap numbers only).
    by_driver = laps.groupby("driver_number")
    next_pit_out = by_driver["is_pit_out_lap"].shift(-1)
    next_lap_no = by_driver["lap_number"].shift(-1)
    laps["is_in_lap"] = next_pit_out.eq(True) & (next_lap_no == laps["lap_number"] + 1)

    # ---- Tyre stint for each lap ----
    stints = stints[[
        "driver_number", "stint_number", "lap_start",
        "lap_end", "compound", "tyre_age_at_start"
    ]].copy()
    stints = stints.dropna(subset=["driver_number", "lap_start"])
    stints["driver_number"] = stints["driver_number"].astype(int)
    stints["lap_start"] = stints["lap_start"].astype(int)
    stints["lap_end"] = pd.to_numeric(stints["lap_end"], errors="coerce").fillna(9999)
    stints["tyre_age_at_start"] = pd.to_numeric(stints["tyre_age_at_start"], errors="coerce")

    # merge_asof needs BOTH frames sorted globally by their merge key.
    laps = pd.merge_asof(
        laps.sort_values(["lap_number", "driver_number"]),
        stints.sort_values(["lap_start", "driver_number"]),
        left_on="lap_number", right_on="lap_start",
        by="driver_number", direction="backward"
    )

    beyond_stint = laps["lap_number"] > laps["lap_end"]
    laps.loc[
        beyond_stint,
        ["compound", "tyre_age_at_start", "stint_number", "lap_start"]
    ] = np.nan

    laps["TyreLife"] = laps["tyre_age_at_start"] + laps["lap_number"] - laps["lap_start"] + 1
    laps["FreshTyre"] = laps["tyre_age_at_start"].eq(0)
    laps["Compound"] = laps["compound"].astype("string").str.upper()

    laps = laps.sort_values(["driver_number", "lap_number"]).reset_index(drop=True)

    # ---- Driver and team ----
    drivers = drivers.dropna(subset=["driver_number"]).drop_duplicates("driver_number")
    numbers = drivers["driver_number"].astype(int)
    laps["Driver"] = laps["driver_number"].map(dict(zip(numbers, drivers["name_acronym"])))
    laps["Team"] = laps["driver_number"].map(dict(zip(numbers, drivers["team_name"])))

    # ---- Weather: latest reading at or before lap start, never from the future ----
    laps["TrackTemp"] = np.nan
    laps["AirTemp"] = np.nan
    laps["Rainfall"] = np.nan

    weather_cols = {"date", "track_temperature", "air_temperature", "rainfall"}
    if not weather.empty and weather_cols <= set(weather.columns):
        w = weather[sorted(weather_cols)].copy()
        w["date"] = to_utc(w["date"])
        w = w.dropna(subset=["date"]).sort_values("date")
        w = w.rename(columns={
            "date": "_w_date", "track_temperature": "_w_track",
            "air_temperature": "_w_air", "rainfall": "_w_rain",
        })
        w["_w_track"] = pd.to_numeric(w["_w_track"], errors="coerce")
        w["_w_air"] = pd.to_numeric(w["_w_air"], errors="coerce")
        w["_w_rain"] = parse_rain(w["_w_rain"])

        timed = laps.loc[laps["date_start"].notna(), ["date_start"]].copy()
        timed["_idx"] = timed.index
        timed = timed.sort_values("date_start")

        if not w.empty and not timed.empty:
            matched = pd.merge_asof(
                timed, w,
                left_on="date_start", right_on="_w_date",
                direction="backward", tolerance=WEATHER_TOLERANCE
            )
            idx = matched["_idx"].to_numpy()
            laps.loc[idx, "TrackTemp"] = matched["_w_track"].to_numpy()
            laps.loc[idx, "AirTemp"] = matched["_w_air"].to_numpy()
            laps.loc[idx, "Rainfall"] = matched["_w_rain"].to_numpy()

    # ---- Safety car, VSC and red flag laps ----
    lap_end = laps["date_start"] + pd.to_timedelta(laps["lap_duration"], unit="s")
    valid_ends = lap_end.dropna()
    race_end = valid_ends.max() if not valid_ends.empty else pd.NaT

    windows = build_windows(control, race_end)
    laps["InSafetyCar"] = False
    for win in windows:
        hit = (laps["date_start"] < win["end"]) & (lap_end > win["start"])
        laps.loc[hit.fillna(False), "InSafetyCar"] = True

    window_rows = pd.DataFrame([
        {
            "Year": year, "Round": rnd, "Circuit": circuit, "SessionKey": key,
            "kind": w["kind"], "start": w["start"], "end": w["end"],
            "minutes": round((w["end"] - w["start"]).total_seconds() / 60, 1),
            "how_closed": w["how_closed"],
        }
        for w in windows
    ], columns=WINDOW_COLUMNS)

    inferred = int(window_rows["how_closed"].isin(["cap", "race_end"]).sum())
    log["rc_windows"] = len(windows)
    log["rc_red_windows"] = int((window_rows["kind"] == "RED").sum())
    log["rc_windows_inferred"] = inferred
    log["sc_share"] = round(float(laps["InSafetyCar"].mean()), 3)

    # ---- Race level screens: weather and tyres ----
    rain_known = laps["Rainfall"].notna()
    weather_ok = laps[["TrackTemp", "AirTemp", "Rainfall"]].notna().all(axis=1)
    weather_coverage = float(weather_ok.mean())
    wet_lap_share = (
        float((laps.loc[rain_known, "Rainfall"] > 0).mean()) if rain_known.any() else np.nan
    )

    compound = laps["Compound"].astype(object)
    compound_known = compound.notna()
    wet_tyre_share = (
        float(compound[compound_known].isin(["INTERMEDIATE", "WET"]).mean())
        if compound_known.any() else np.nan
    )

    log["weather_coverage"] = round(weather_coverage, 3)
    log["wet_lap_share"] = round(wet_lap_share, 3) if pd.notna(wet_lap_share) else np.nan
    log["wet_tyre_share"] = round(wet_tyre_share, 3) if pd.notna(wet_tyre_share) else np.nan

    if weather_coverage < MIN_WEATHER_COVERAGE:
        return excluded(log, "weather data missing", window_rows)
    if (pd.notna(wet_lap_share) and wet_lap_share > MAX_WET_LAP_SHARE) or \
       (pd.notna(wet_tyre_share) and wet_tyre_share > MAX_WET_TYRE_SHARE):
        return excluded(log, "wet race", window_rows)

    # ---- Each lap's own stint median (normal racing laps only) ----
    reference_ok = (
        laps["lap_duration"].notna()
        & ~laps["is_pit_out_lap"] & ~laps["is_in_lap"]
        & ~laps["InSafetyCar"]
        & (laps["lap_number"] > 1)
    )
    reference = laps["lap_duration"].where(reference_ok)
    laps["StintMedian"] = reference.groupby(
        [laps["driver_number"], laps["stint_number"]]
    ).transform("median")

    # ---- Target and next-lap context, joined on the exact next lap number ----
    laps = attach_next(laps, NEXT_FIELDS)

    # ---- Cleaning rules, each one counted ----
    next_missing = laps["NextLapNumber"].isna()

    masks = {
        "no_time": laps["lap_duration"].isna(),
        "no_driver": laps["Driver"].isna(),
        "lap_1": laps["lap_number"] <= 1,
        "no_next_lap": next_missing,
        "nonconsecutive_target": (~next_missing) & (laps["NextLapNumber"] != laps["lap_number"] + 1),
        "no_target": (~next_missing) & laps["NextLapSeconds"].isna(),
        "pit": (
            laps["is_pit_out_lap"] | laps["is_in_lap"]
            | laps["NextIsPitOut"].ne(False) | laps["NextIsInLap"].ne(False)
        ),
        "no_tyre": laps["Compound"].isna() | laps["TyreLife"].isna(),
        "no_weather": laps[["TrackTemp", "AirTemp", "Rainfall"]].isna().any(axis=1),
        "rain": laps["Rainfall"] > 0,
        "safety_car": laps["InSafetyCar"] | laps["NextInSafetyCar"].ne(False),
        "no_next_ref": (~next_missing) & laps["NextStintMedian"].isna(),
        # Each lap is compared with its OWN stint's median, so a next lap in a new stint is judged fairly.
        "slow": (
            (laps["lap_duration"] > laps["StintMedian"] * SLOW_FACTOR)
            | (laps["NextLapSeconds"] > laps["NextStintMedian"] * SLOW_FACTOR)
        ),
    }

    drop = pd.concat(list(masks.values()), axis=1).any(axis=1)
    clean = laps[~drop].copy()

    # One lap can break several rules, so these counts overlap and will not sum to the total.
    for name, mask in masks.items():
        log[f"n_{name}"] = int(mask.sum())

    clean["Year"] = year
    clean["Round"] = rnd
    clean["Circuit"] = circuit
    clean["LapSeconds"] = clean["lap_duration"]
    clean["LapNumber"] = clean["lap_number"]
    clean["Stint"] = clean["stint_number"].astype(int)
    clean["TyreLife"] = clean["TyreLife"].astype(int)
    clean["NextLapNumber"] = clean["NextLapNumber"].astype(int)

    log["prediction_rows"] = len(clean)
    log["pct_removed"] = round(100 * (1 - len(clean) / raw_laps), 2)
    log["needs_review"] = bool(inferred > 0 or dup_laps > 0)

    print(f"   kept {len(clean)} of {raw_laps} laps ({log['pct_removed']}% removed)")

    if len(clean) < MIN_ROWS:
        return excluded(log, "too few rows after cleaning", window_rows)

    return clean[COLUMNS], log, window_rows


# --------------------------------------------------------------------------
# Validation and comparison
# --------------------------------------------------------------------------
def validate_dataset(data):
    """Checks that must pass before the file is trusted. Returns True if all hard checks pass."""
    print("\nValidation:")
    ok = True

    missing = [c for c in COLUMNS if c not in data.columns]
    if missing:
        print(f"  FAIL: missing columns {missing}")
        return False

    mismatch = int((data["NextLapNumber"] != data["LapNumber"] + 1).sum())
    print(f"  target is the very next lap: {'ok' if mismatch == 0 else 'FAIL'} ({mismatch} bad rows)")
    ok &= mismatch == 0

    dupes = int(data.duplicated(["Year", "Round", "Driver", "LapNumber"]).sum())
    print(f"  duplicate driver/race/lap keys: {'ok' if dupes == 0 else 'FAIL'} ({dupes})")
    ok &= dupes == 0

    nans = int(data[COLUMNS].isna().sum().sum())
    print(f"  missing values: {'ok' if nans == 0 else 'FAIL'} ({nans})")
    ok &= nans == 0

    d = data.sort_values(["Year", "Round", "Driver", "Stint", "LapNumber"])
    g = d.groupby(["Year", "Round", "Driver", "Stint"])
    tyre_step = g["TyreLife"].diff()
    lap_step = g["LapNumber"].diff()
    tyre_bad = int(((tyre_step != lap_step) & tyre_step.notna()).sum())
    print(f"  tyre age steps match lap steps within a stint: {tyre_bad} mismatches (warning only)")

    return bool(ok)


def inspect_session(session_key):
    """Show how every race control message of one session is classified, plus the resulting windows."""
    control = get("race_control", session_key=session_key)
    if control.empty:
        print("No race control data.")
        return

    control = control.copy()
    control["date"] = to_utc(control["date"])
    control = control.sort_values("date")
    flags = control["flag"] if "flag" in control.columns else pd.Series("", index=control.index)

    print(f"{'time (UTC)':<26}{'flag':<14}{'event':<12}message")
    for t, flag, msg in zip(control["date"], flags, control["message"]):
        event = classify_event(msg, flag)
        print(f"{str(t)[:25]:<26}{str(flag)[:12]:<14}{event:<12}{msg}")

    print("\nWindows built from these messages:")
    for win in build_windows(control, pd.NaT):
        minutes = (win["end"] - win["start"]).total_seconds() / 60
        print(f"  {win['kind']:<4} {str(win['start'])[:19]} -> {str(win['end'])[:19]}"
              f"  {minutes:5.1f} min  closed by: {win['how_closed']}")


def compare_with_old():
    if not (os.path.exists(OLD_DATA) and os.path.exists(OUTPUT_DATA)):
        print(f"Need both {OLD_DATA} and {OUTPUT_DATA}.")
        return

    old = pd.read_csv(OLD_DATA)
    new = pd.read_csv(OUTPUT_DATA)
    key = ["Year", "Round", "Driver", "LapNumber"]

    print(f"old rows: {len(old)}   new rows: {len(new)}")
    print("\nRows per season (old vs new):")
    print(pd.concat(
        [old.groupby("Year").size().rename("old"), new.groupby("Year").size().rename("new")],
        axis=1
    ).fillna(0).astype(int))

    merged = old[key + ["LapSeconds", "NextLapSeconds"]].merge(
        new[key + ["LapSeconds", "NextLapSeconds"]],
        on=key, how="outer", indicator=True, suffixes=("_old", "_new")
    )
    print("\nRow overlap:")
    print(merged["_merge"].value_counts().to_string())

    both = merged[merged["_merge"] == "both"]
    for col in ["LapSeconds", "NextLapSeconds"]:
        diff = (both[f"{col}_old"] - both[f"{col}_new"]).abs().max()
        print(f"largest {col} difference on shared rows: {diff}")

    only_old = merged[merged["_merge"] == "left_only"]
    print("\nRaces that lost the most rows (in old, not in new):")
    print(only_old.groupby(["Year", "Round"]).size().sort_values(ascending=False).head(10).to_string())

    only_new = merged[merged["_merge"] == "right_only"]
    print("\nRaces that gained the most rows (in new, not in old):")
    print(only_new.groupby(["Year", "Round"]).size().sort_values(ascending=False).head(10).to_string())


# --------------------------------------------------------------------------
# Main build loop
# --------------------------------------------------------------------------
def main():
    os.makedirs(PARTS_DIR, exist_ok=True)

    races = list_races()
    print(f"{len(races)} finished races found")

    frames, logs, windows_list, skipped = [], [], [], []
    fails_in_a_row = 0

    for i, (year, rnd, circuit, key) in enumerate(races, 1):
        data_path = f"{PARTS_DIR}/{key}_laps.csv"
        log_path = f"{PARTS_DIR}/{key}_log.csv"
        win_path = f"{PARTS_DIR}/{key}_windows.csv"

        if all(os.path.exists(p) for p in (data_path, log_path, win_path)):
            cached_windows = pd.read_csv(win_path)
            if not cached_windows.empty:
                cached_minutes = pd.to_numeric(cached_windows["minutes"], errors="coerce")
                if (cached_minutes < 0).any():
                    print(f"[{i}/{len(races)}] {year} round {rnd}: rebuilding cache with invalid race-control window")
                else:
                    frames.append(pd.read_csv(data_path))
                    logs.append(pd.read_csv(log_path).iloc[0].to_dict())
                    windows_list.append(cached_windows)
                    continue
            else:
                frames.append(pd.read_csv(data_path))
                logs.append(pd.read_csv(log_path).iloc[0].to_dict())
                windows_list.append(cached_windows)
                continue

        print(f"[{i}/{len(races)}] {year} round {rnd}: {circuit}")

        try:
            clean, log, win_df = get_clean_laps(year, rnd, circuit, key)
        except Exception as e:
            print(f"   SKIPPED: {e}")
            skipped.append((year, rnd, circuit, key, str(e)))
            fails_in_a_row += 1
            if fails_in_a_row >= MAX_FAILURES_IN_A_ROW:
                print("Stopping after consecutive failures.")
                break
            continue

        fails_in_a_row = 0

        if log.get("excluded"):
            print(f"   EXCLUDED: {log['excluded']}")

        # Excluded races are saved too (as empty data), so a re-run does not download them again.
        clean.to_csv(data_path, index=False)
        pd.DataFrame([log]).to_csv(log_path, index=False)
        win_df.to_csv(win_path, index=False)

        frames.append(clean)
        logs.append(log)
        windows_list.append(win_df)

    frames = [f for f in frames if len(f)]
    if not frames:
        raise SystemExit("No races were loaded.")

    data = pd.concat(frames, ignore_index=True)
    log_df = pd.DataFrame(logs)
    log_df["excluded"] = log_df["excluded"].fillna("")
    if "needs_review" in log_df.columns:
        log_df["needs_review"] = parse_bool(log_df["needs_review"].astype(object))

    non_empty_windows = [w for w in windows_list if len(w)]
    windows_all = (
        pd.concat(non_empty_windows, ignore_index=True)
        if non_empty_windows else pd.DataFrame(columns=WINDOW_COLUMNS)
    )

    dropped = log_df[log_df["excluded"] != ""]
    kept = log_df[log_df["excluded"] == ""]

    print(f"\nRaces processed: {len(log_df)}   kept: {len(kept)}   excluded: {len(dropped)}")
    print(f"Prediction rows: {len(data)}")

    print("\nRows per season:")
    print(data.groupby("Year").size().to_string())

    if len(dropped):
        print("\nExcluded races (reason is in the log):")
        print(dropped[["Year", "Round", "Circuit", "excluded"]].to_string(index=False))

    if "needs_review" in log_df.columns:
        review = log_df[log_df["needs_review"]]
        if len(review):
            print("\nRaces with a safety car / red flag window that had no observed end marker (check these):")
            print(review[["Year", "Round", "Circuit", "rc_windows_inferred"]].to_string(index=False))

    if len(windows_all):
        print("\nHow race control windows were closed:")
        print(windows_all["how_closed"].value_counts().to_string())

    persistence = (data["NextLapSeconds"] - data["LapSeconds"]).abs().mean()
    print(f"\nPersistence baseline (next lap = this lap), MAE: {persistence:.3f} s")

    passed = validate_dataset(data)

    if skipped:
        print("\nSkipped races (errors):")
        for item in skipped:
            print(item)
        pd.DataFrame(
            skipped, columns=["Year", "Round", "Circuit", "SessionKey", "error"]
        ).to_csv(OUTPUT_SKIPPED, index=False)

    if not passed:
        raise SystemExit("Validation failed: no validated output files were written. Do not use this dataset until the failures are explained.")

    # Only publish the dataset and audit reports after all hard validation checks pass.
    data.to_csv(OUTPUT_DATA, index=False)
    log_df.to_csv(OUTPUT_LOG, index=False)
    windows_all.to_csv(OUTPUT_WINDOWS, index=False)
    dropped[["Year", "Round", "Circuit", "excluded"]].to_csv(OUTPUT_EXCLUDED, index=False)

    print(f"\nSaved validated outputs: {OUTPUT_DATA}, {OUTPUT_LOG}, {OUTPUT_WINDOWS}, {OUTPUT_EXCLUDED}")


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "build"

    if command == "build":
        main()
    elif command == "inspect" and len(sys.argv) > 2:
        inspect_session(int(sys.argv[2]))
    elif command == "compare":
        compare_with_old()
    else:
        print(__doc__)