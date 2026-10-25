import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

BASE = "https://api.openf1.org/v1"
PAUSE = 0.7
PARTS_DIR = Path("race_parts_openf1_v3")

START_YEAR = 2023
END_YEAR = pd.Timestamp.today().year
MAX_FAILURES_IN_A_ROW = 3

# Cleaning settings. These define the population this dataset represents:
# mostly ordinary, dry, green-flag laps rather than every possible race event.
SLOW_FACTOR = 1.10
SC_MAX_MINUTES = 30
RED_MAX_MINUTES = 60
MIN_COVERAGE = 0.75
MIN_WEATHER_COVERAGE = 0.50
MAX_WET_LAP_SHARE = 0.10
MAX_WET_TYRE_SHARE = 0.02
MIN_ROWS = 300

COLUMNS = [
    "Driver", "Team", "Year", "Round", "Circuit",
    "Compound", "TyreLife", "FreshTyre", "Stint",
    "LapNumber", "TrackTemp", "AirTemp", "Rainfall",
    "InSafetyCar", "LapSeconds", "NextLapNumber", "NextLapSeconds",
]


def parse_bool(value):
    """Parse booleans safely, including strings such as 'false' and '0'."""
    if pd.isna(value):
        return False
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer, float, np.floating)):
        return bool(value) if value in (0, 1) else False
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n", "", "none", "nan"}:
        return False
    return False


def get(endpoint, **params):
    """Fetch an OpenF1 endpoint with retries for transient failures."""
    for attempt in range(6):
        try:
            response = requests.get(
                f"{BASE}/{endpoint}", params=params, timeout=60
            )
        except requests.RequestException as exc:
            if attempt == 5:
                raise RuntimeError(
                    f"Request failed after retries: {endpoint} {params}: {exc}"
                ) from exc
            time.sleep(5 * (attempt + 1))
            continue

        if response.status_code == 404:
            return pd.DataFrame()
        if response.status_code == 429 or response.status_code >= 500:
            if attempt == 5:
                response.raise_for_status()
            time.sleep(10 * (attempt + 1))
            continue

        response.raise_for_status()
        time.sleep(PAUSE)
        payload = response.json()
        return pd.DataFrame(payload if isinstance(payload, list) else [])

    raise RuntimeError(f"Request failed: {endpoint} {params}")


def list_races():
    """Return completed Race sessions, with rounds numbered chronologically."""
    now = pd.Timestamp.now(tz="UTC")
    races = []

    for year in range(START_YEAR, END_YEAR + 1):
        df = get("sessions", year=year, session_name="Race")
        if df.empty or "date_end" not in df.columns:
            continue

        df["date_end"] = pd.to_datetime(df["date_end"], utc=True, errors="coerce")
        df = df[df["date_end"] < now].copy()

        if "is_cancelled" in df.columns:
            cancelled = df["is_cancelled"].map(parse_bool)
            df = df[~cancelled].copy()

        if df.empty:
            continue

        df["date_start"] = pd.to_datetime(
            df.get("date_start"), utc=True, errors="coerce"
        )
        df = df.sort_values("date_start").reset_index(drop=True)

        for rnd, row in enumerate(df.itertuples(index=False), 1):
            session_key = getattr(row, "session_key", None)
            circuit = getattr(row, "circuit_short_name", None)
            if pd.isna(session_key) or circuit is None or pd.isna(circuit):
                continue
            races.append((year, rnd, str(circuit), int(session_key)))

    return races


def safety_car_periods(control, race_end):
    """Approximate SC/VSC/red-flag windows from race-control messages.

    Returns (periods, capped_count, fallback_closed_count). The intervals are
    approximate: OpenF1 race-control messages do not always provide a clean pair
    of start/end events.
    """
    if control.empty or not {"date", "message"}.issubset(control.columns):
        return [], 0, 0

    rc = control.copy()
    rc["date"] = pd.to_datetime(rc["date"], utc=True, errors="coerce")
    rc = rc.dropna(subset=["date"]).sort_values("date")

    periods = []
    capped = 0
    fallback_closed = 0
    start = None
    kind = None

    def close_window(end, cap_applied=False, fallback=False):
        nonlocal start, kind, capped, fallback_closed
        if start is None or pd.isna(end) or end < start:
            start, kind = None, None
            return
        periods.append((start, end))
        if cap_applied:
            capped += 1
        if fallback:
            fallback_closed += 1
        start, kind = None, None

    for _, event in rc.iterrows():
        msg = str(event["message"]).strip().upper()
        t = event["date"]

        # Explicit transition from red flag to safety-car phase.
        if start is not None and kind == "red" and msg.startswith("SAFETY CAR LIGHTS ON"):
            close_window(t)
            start, kind = t, "sc"
            continue

        # If a cap is exceeded, close the old interval at its cap before
        # interpreting the current message as a possible new interval.
        if start is not None:
            limit = RED_MAX_MINUTES if kind == "red" else SC_MAX_MINUTES
            cap_end = start + pd.Timedelta(minutes=limit)
            if t > cap_end:
                close_window(cap_end, cap_applied=True, fallback=True)

        is_red = msg.startswith("RED FLAG")
        is_sc = "SAFETY CAR" in msg or "VSC" in msg
        starts_sc = is_sc and ("DEPLOY" in msg or "LIGHTS ON" in msg)

        if start is None:
            if is_red:
                start, kind = t, "red"
            elif starts_sc:
                start, kind = t, "sc"
            continue

        # A red flag interrupts an active SC/VSC period.
        if kind == "sc" and is_red:
            close_window(t)
            start, kind = t, "red"
            continue

        # Some feeds explicitly announce the safety-car phase after a red flag.
        if kind == "red" and starts_sc:
            close_window(t)
            start, kind = t, "sc"
            continue

        ends_sc = kind == "sc" and is_sc and any(
            phrase in msg
            for phrase in ("IN THIS LAP", "ENDING", "ENDED", "WITHDRAWN")
        )

        # Do NOT match a generic 'RESUME' prefix: 'RACE WILL RESUME AT ...'
        # is an announcement, not proof that the red flag has ended.
        ends_red = kind == "red" and (
            msg.startswith("GREEN LIGHT")
            or msg.startswith("PIT EXIT OPEN")
            or msg.startswith("RESTART")
            or msg.startswith("SESSION RESUMED")
        )

        if ends_sc or ends_red:
            close_window(t)

    # Close a remaining window at the earlier of its cap and race end.
    if start is not None:
        limit = RED_MAX_MINUTES if kind == "red" else SC_MAX_MINUTES
        cap_end = start + pd.Timedelta(minutes=limit)
        end = cap_end
        cap_applied = True
        if pd.notna(race_end) and race_end <= cap_end:
            end = race_end
            cap_applied = False
        close_window(end, cap_applied=cap_applied, fallback=True)

    return periods, capped, fallback_closed


def excluded(log, reason):
    result = dict(log)
    result["excluded"] = reason
    result["prediction_rows"] = 0
    return pd.DataFrame(columns=COLUMNS), result


def get_clean_laps(year, rnd, circuit, session_key):
    laps = get("laps", session_key=session_key)
    if laps.empty:
        raise RuntimeError("No lap data")

    stints = get("stints", session_key=session_key)
    drivers = get("drivers", session_key=session_key)
    weather = get("weather", session_key=session_key)
    control = get("race_control", session_key=session_key)

    if stints.empty:
        raise RuntimeError("No tyre stint data")

    required_lap_columns = {
        "driver_number", "lap_number", "date_start",
        "lap_duration", "is_pit_out_lap",
    }
    missing = required_lap_columns - set(laps.columns)
    if missing:
        raise RuntimeError(f"Lap endpoint missing required columns: {sorted(missing)}")

    laps = laps[list(required_lap_columns)].copy()
    laps = laps.dropna(subset=["driver_number", "lap_number"])
    laps["driver_number"] = pd.to_numeric(laps["driver_number"], errors="coerce")
    laps["lap_number"] = pd.to_numeric(laps["lap_number"], errors="coerce")
    laps = laps.dropna(subset=["driver_number", "lap_number"])
    laps["driver_number"] = laps["driver_number"].astype(int)
    laps["lap_number"] = laps["lap_number"].astype(int)
    laps["date_start"] = pd.to_datetime(laps["date_start"], utc=True, errors="coerce")
    laps["is_pit_out_lap"] = laps["is_pit_out_lap"].map(parse_bool)
    laps["lap_duration"] = pd.to_numeric(laps["lap_duration"], errors="coerce")
    laps = laps.sort_values(["driver_number", "lap_number", "date_start"])
    # One row per driver/lap is required for reliable shifts and targets.
    duplicate_keys = laps.duplicated(["driver_number", "lap_number"], keep="first")
    duplicate_laps = int(duplicate_keys.sum())
    laps = laps.loc[~duplicate_keys].reset_index(drop=True)

    raw_laps = len(laps)
    n_drivers = laps["driver_number"].nunique()
    race_length = int(laps["lap_number"].max()) if raw_laps else 0
    coverage = raw_laps / max(n_drivers * race_length, 1)
    log = {
        "Year": year, "Round": rnd, "Circuit": circuit,
        "session_key": session_key, "raw_laps": raw_laps,
        "duplicate_laps_removed": duplicate_laps,
        "coverage": round(float(coverage), 3), "excluded": "",
    }

    if coverage < MIN_COVERAGE:
        return excluded(log, "incomplete lap data")

    # Determine in-laps and targets before removing any rows.
    laps["is_in_lap"] = (
        laps.groupby("driver_number")["is_pit_out_lap"]
        .shift(-1).fillna(False).astype(bool)
    )
    grouped = laps.groupby("driver_number", sort=False)
    laps["NextLapSeconds"] = grouped["lap_duration"].shift(-1)
    laps["NextLapNumber"] = grouped["lap_number"].shift(-1)
    laps["NextLapIsPitOut"] = (
        grouped["is_pit_out_lap"].shift(-1).fillna(True).astype(bool)
    )
    laps["NextLapIsInLap"] = (
        grouped["is_in_lap"].shift(-1).fillna(True).astype(bool)
    )
    laps["target_is_consecutive"] = laps["NextLapNumber"].eq(laps["lap_number"] + 1)

    # Attach the tyre stint active on each lap. Sort globally by merge key for
    # pandas.merge_asof; the driver number is the grouping key, not the sort key.
    stint_cols = [
        "driver_number", "stint_number", "lap_start", "lap_end",
        "compound", "tyre_age_at_start",
    ]
    missing_stint_cols = set(stint_cols) - set(stints.columns)
    if missing_stint_cols:
        raise RuntimeError(f"Stint endpoint missing columns: {sorted(missing_stint_cols)}")
    stints = stints[stint_cols].copy()
    stints["driver_number"] = pd.to_numeric(stints["driver_number"], errors="coerce")
    stints["lap_start"] = pd.to_numeric(stints["lap_start"], errors="coerce")
    stints["lap_end"] = pd.to_numeric(stints["lap_end"], errors="coerce")
    stints = stints.dropna(subset=["driver_number", "lap_start"])
    stints["driver_number"] = stints["driver_number"].astype(int)
    stints["lap_start"] = stints["lap_start"].astype(int)
    stints["lap_end"] = stints["lap_end"].fillna(9999)
    stints = stints.sort_values(["lap_start", "driver_number"]).reset_index(drop=True)

    laps = pd.merge_asof(
        laps.sort_values(["lap_number", "driver_number"]),
        stints,
        left_on="lap_number", right_on="lap_start",
        by="driver_number", direction="backward",
    )
    beyond = laps["lap_number"] > laps["lap_end"]
    laps.loc[beyond, ["compound", "tyre_age_at_start", "stint_number", "lap_start"]] = np.nan
    laps["TyreLife"] = (
        pd.to_numeric(laps["tyre_age_at_start"], errors="coerce")
        + laps["lap_number"] - laps["lap_start"] + 1
    )
    laps["FreshTyre"] = pd.to_numeric(laps["tyre_age_at_start"], errors="coerce").eq(0)
    laps["Compound"] = laps["compound"].astype("string").str.upper()

    # Driver/team metadata. Missing metadata stays missing and is logged via masks.
    if not drivers.empty and {"driver_number", "name_acronym", "team_name"}.issubset(drivers.columns):
        driver_meta = drivers.drop_duplicates("driver_number").copy()
        driver_meta["driver_number"] = pd.to_numeric(driver_meta["driver_number"], errors="coerce")
        driver_meta = driver_meta.dropna(subset=["driver_number"])
        driver_meta["driver_number"] = driver_meta["driver_number"].astype(int)
        acronym = dict(zip(driver_meta["driver_number"], driver_meta["name_acronym"]))
        team = dict(zip(driver_meta["driver_number"], driver_meta["team_name"]))
        laps["Driver"] = laps["driver_number"].map(acronym)
        laps["Team"] = laps["driver_number"].map(team)
    else:
        laps["Driver"] = np.nan
        laps["Team"] = np.nan

    # Backward-as-of weather join: never attach a reading from the future.
    for column in ("TrackTemp", "AirTemp", "Rainfall"):
        laps[column] = np.nan
    if not weather.empty and {"date", "track_temperature", "air_temperature", "rainfall"}.issubset(weather.columns):
        w = weather[["date", "track_temperature", "air_temperature", "rainfall"]].copy()
        w["date"] = pd.to_datetime(w["date"], utc=True, errors="coerce")
        w = w.dropna(subset=["date"]).sort_values("date")
        timed = laps[laps["date_start"].notna()].copy()
        untimed = laps[laps["date_start"].isna()].copy()
        if not w.empty and not timed.empty:
            timed = pd.merge_asof(
                timed.sort_values("date_start"), w,
                left_on="date_start", right_on="date", direction="backward",
            )
            timed["TrackTemp"] = pd.to_numeric(timed["track_temperature"], errors="coerce")
            timed["AirTemp"] = pd.to_numeric(timed["air_temperature"], errors="coerce")
            # OpenF1 rainfall may be boolean or numeric depending on response/schema.
            rainfall = timed["rainfall"]
            timed["Rainfall"] = rainfall.map(parse_bool).astype(float)
            numeric_rain = pd.to_numeric(rainfall, errors="coerce")
            timed.loc[numeric_rain.notna(), "Rainfall"] = numeric_rain[numeric_rain.notna()]
        laps = pd.concat([timed, untimed], ignore_index=True, sort=False)

    # Restore driver/lap ordering after joins; all subsequent shifts depend on it.
    laps = laps.sort_values(["driver_number", "lap_number", "date_start"]).reset_index(drop=True)

    lap_end = laps["date_start"] + pd.to_timedelta(laps["lap_duration"], unit="s")
    valid_ends = lap_end.dropna()
    race_end = valid_ends.max() if not valid_ends.empty else pd.NaT
    periods, capped, fallback_closed = safety_car_periods(control, race_end)
    laps["InSafetyCar"] = False
    for start, end in periods:
        overlap = (laps["date_start"] < end) & (lap_end > start)
        laps.loc[overlap.fillna(False), "InSafetyCar"] = True
    # This flag includes safety car, VSC, and red-flag intervals; the output
    # column name is retained for compatibility with the existing model script.
    laps["NextInSafetyCar"] = (
        laps.groupby("driver_number")["InSafetyCar"]
        .shift(-1).fillna(True).astype(bool)
    )

    # Wet-race screen uses known rainfall readings only. Missing weather is not dry.
    known_rain = laps["Rainfall"].notna()
    weather_coverage = float(known_rain.mean()) if len(laps) else 0.0
    wet_lap_share = float((laps.loc[known_rain, "Rainfall"] > 0).mean()) if known_rain.any() else np.nan
    wet_tyre_share = float(laps["Compound"].isin(["INTERMEDIATE", "WET"]).mean())
    log["weather_coverage"] = round(weather_coverage, 3)
    log["wet_lap_share"] = round(wet_lap_share, 3) if pd.notna(wet_lap_share) else np.nan
    log["wet_tyre_share"] = round(wet_tyre_share, 3)
    log["sc_share"] = round(float(laps["InSafetyCar"].mean()), 3)
    log["sc_windows"] = len(periods)
    log["sc_windows_capped"] = capped
    log["sc_windows_fallback_closed"] = fallback_closed

    if weather_coverage < MIN_WEATHER_COVERAGE:
        return excluded(log, "insufficient weather coverage")
    if wet_lap_share > MAX_WET_LAP_SHARE or wet_tyre_share > MAX_WET_TYRE_SHARE:
        return excluded(log, "wet race")

    # Stint medians exclude pit/in/out and safety-car laps. These medians are
    # cleaning references, not model features. The filter intentionally focuses
    # this dataset on ordinary pace laps, not rare slow events.
    reference_ok = (
        laps["lap_duration"].notna()
        & ~laps["is_pit_out_lap"]
        & ~laps["is_in_lap"]
        & ~laps["InSafetyCar"]
    )
    reference = laps["lap_duration"].where(reference_ok)
    stint_median = reference.groupby([laps["driver_number"], laps["stint_number"]]).transform("median")

    # Find the median belonging to the target lap, not necessarily the current stint.
    next_stint_median = (
        stint_median.groupby(laps["driver_number"], sort=False).shift(-1)
    )
    next_stint_median = next_stint_median.where(laps["target_is_consecutive"])

    masks = {
        "no_time": laps["lap_duration"].isna(),
        "no_target": laps["NextLapSeconds"].isna(),
        "nonconsecutive_target": ~laps["target_is_consecutive"],
        "no_driver": laps["Driver"].isna() | laps["Team"].isna(),
        "lap_1": laps["lap_number"] <= 1,
        "pit": (
            laps["is_pit_out_lap"] | laps["is_in_lap"]
            | laps["NextLapIsPitOut"] | laps["NextLapIsInLap"]
        ),
        "no_tyre": (
            laps["Compound"].isna()
            | laps["TyreLife"].isna()
            | laps["stint_number"].isna()
        ),
        "safety_car": laps["InSafetyCar"] | laps["NextInSafetyCar"],
        "rain": laps["Rainfall"].notna() & (laps["Rainfall"] > 0),
        "slow": (
            (stint_median.notna() & (laps["lap_duration"] > stint_median * SLOW_FACTOR))
            | (next_stint_median.notna() & (laps["NextLapSeconds"] > next_stint_median * SLOW_FACTOR))
        ),
    }

    drop = pd.concat(masks, axis=1).any(axis=1)
    clean = laps.loc[~drop].copy()
    for name, mask in masks.items():
        log[f"n_{name}"] = int(mask.sum())

    clean["Year"] = year
    clean["Round"] = rnd
    clean["Circuit"] = circuit
    clean["LapSeconds"] = clean["lap_duration"]
    clean["LapNumber"] = clean["lap_number"]
    clean["Stint"] = clean["stint_number"]

    log["prediction_rows"] = len(clean)
    log["pct_removed"] = round(100 * (1 - len(clean) / max(raw_laps, 1)), 2)
    print(f"   kept {len(clean)} of {raw_laps} laps ({log['pct_removed']}% removed)")

    if len(clean) < MIN_ROWS:
        return excluded(log, "too few rows after cleaning")

    # Final invariant checks before writing a race part.
    if not (clean["NextLapNumber"] == clean["LapNumber"] + 1).all():
        raise RuntimeError("Internal validation failed: nonconsecutive target survived cleaning")
    if clean.duplicated(["Driver", "Year", "Round", "LapNumber"]).any():
        raise RuntimeError("Internal validation failed: duplicate driver/race/lap rows")

    return clean[COLUMNS], log


def main():
    PARTS_DIR.mkdir(parents=True, exist_ok=True)
    races = list_races()
    print(f"{len(races)} finished races found")

    frames = []
    logs = []
    skipped = []
    fails_in_a_row = 0

    for i, (year, rnd, circuit, session_key) in enumerate(races, 1):
        data_path = PARTS_DIR / f"{session_key}_laps.csv"
        log_path = PARTS_DIR / f"{session_key}_log.csv"

        if data_path.exists() and log_path.exists():
            try:
                cached_data = pd.read_csv(data_path)
                cached_log_df = pd.read_csv(log_path)
                if cached_log_df.empty:
                    raise ValueError("empty cached log")
                cached_log = cached_log_df.iloc[0].to_dict()
                # Only reuse cache entries with the expected output schema.
                if list(cached_data.columns) != COLUMNS:
                    raise ValueError("cached data schema mismatch")
                frames.append(cached_data)
                logs.append(cached_log)
                continue
            except Exception as exc:
                print(f"   cache invalid for session {session_key}; rebuilding: {exc}")

        print(f"[{i}/{len(races)}] {year} round {rnd}: {circuit}")
        try:
            clean, log = get_clean_laps(year, rnd, circuit, session_key)
        except Exception as exc:
            print(f"   SKIPPED: {exc}")
            skipped.append((year, rnd, circuit, session_key, str(exc)))
            fails_in_a_row += 1
            if fails_in_a_row >= MAX_FAILURES_IN_A_ROW:
                print("Stopping after consecutive failures. Fix the cause and rerun.")
                break
            continue

        fails_in_a_row = 0
        if log.get("excluded"):
            print(f"   EXCLUDED: {log['excluded']}")

        clean.to_csv(data_path, index=False)
        pd.DataFrame([log]).to_csv(log_path, index=False)
        frames.append(clean)
        logs.append(log)

    frames = [frame for frame in frames if len(frame)]
    if not frames:
        raise SystemExit("No usable races were loaded; existing laps_sample.csv was not overwritten.")

    data = pd.concat(frames, ignore_index=True)
    log_df = pd.DataFrame(logs)

    # Dataset-level checks. Write to a temporary file first, so a failed check
    # cannot replace the previous dataset with an invalid one.
    if not set(COLUMNS).issubset(data.columns):
        raise RuntimeError("Dataset output is missing expected columns")
    if not (pd.to_numeric(data["NextLapNumber"], errors="coerce") == pd.to_numeric(data["LapNumber"], errors="coerce") + 1).all():
        raise RuntimeError("Dataset validation failed: nonconsecutive target found")
    if data.duplicated(["Driver", "Year", "Round", "LapNumber"]).any():
        raise RuntimeError("Dataset validation failed: duplicate driver/race/lap rows")

    output_tmp = Path("laps_sample.csv.tmp")
    data.to_csv(output_tmp, index=False)
    output_tmp.replace("laps_sample.csv")
    log_df.to_csv("removal_log.csv", index=False)

    kept = log_df[log_df["excluded"].fillna("") == ""]
    dropped = log_df[log_df["excluded"].fillna("") != ""]
    print(f"\nRaces processed: {len(log_df)}  kept: {len(kept)}  excluded: {len(dropped)}")
    print(f"Prediction rows: {len(data)}")
    print("\nRows per season:")
    print(data.groupby("Year").size())
    if len(dropped):
        print("\nExcluded races:")
        print(dropped[["Year", "Round", "Circuit", "excluded"]].to_string(index=False))
    print("\nMissing values:")
    print(data.isna().sum().to_string())
    persistence = (data["NextLapSeconds"] - data["LapSeconds"]).abs().mean()
    print(f"\nPersistence baseline (next lap = this lap), MAE: {persistence:.3f} s")

    if skipped:
        print("\nSkipped races (errors):")
        for item in skipped:
            print(item)
        pd.DataFrame(
            skipped, columns=["Year", "Round", "Circuit", "session_key", "error"]
        ).to_csv("skipped_races.csv", index=False)

    print("\nSaved laps_sample.csv and removal_log.csv")
    print(f"Race cache directory: {PARTS_DIR}")


if __name__ == "__main__":
    main()
