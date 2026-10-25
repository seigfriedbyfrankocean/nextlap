import os
import time
import pandas as pd
import fastf1

os.makedirs("f1_cache", exist_ok=True)
os.makedirs("race_parts", exist_ok=True)       # one small file per finished race
fastf1.Cache.enable_cache("f1_cache")

START_YEAR = 2023
END_YEAR = pd.Timestamp.today().year           # current season

KEEP_COMPOUNDS = ["SOFT", "MEDIUM", "HARD"]    # drops UNKNOWN, INTERMEDIATE, WET
REMOVE_NON_GREEN = True                        # keep only laps run entirely under green flag

PAUSE_SECONDS = 2                              # short pause between downloads
MAX_FAILURES_IN_A_ROW = 3                      # stop early if downloads keep failing

COLUMNS = ["Driver", "Team", "Year", "Round", "Circuit", "Compound", "TyreLife",
           "FreshTyre", "Stint", "LapNumber", "TrackStatus",
           "TrackTemp", "AirTemp", "Rainfall", "LapSeconds"]


def list_races():
    """Every race that has already happened, from START_YEAR to the current season."""
    today = pd.Timestamp.today().normalize()
    races = []
    for year in range(START_YEAR, END_YEAR + 1):
        schedule = fastf1.get_event_schedule(year, include_testing=False)
        schedule = schedule[schedule["EventDate"] < today]
        for _, ev in schedule.iterrows():
            # Location (e.g. "Monza") stays the same across years, unlike the event name
            races.append((year, int(ev["RoundNumber"]), ev["Location"]))
    return races


def get_clean_laps(year, rnd, circuit):
    session = fastf1.get_session(year, rnd, "R")
    session.load(telemetry=False, weather=True, messages=False)

    # If the download failed, FastF1 only logs a warning; this line then raises
    laps = session.laps.reset_index(drop=True)
    weather = laps.get_weather_data().reset_index(drop=True)
    for col in ["AirTemp", "TrackTemp", "Rainfall"]:
        laps[col] = weather[col]

    steps = [
        ("pit_laps",  lambda l: l.pick_wo_box()),
        ("slow_laps", lambda l: l.pick_quicklaps()),
        ("lap_1",     lambda l: l[l["LapNumber"] > 1]),
        ("no_time",   lambda l: l.dropna(subset=["LapTime"])),
    ]
    if REMOVE_NON_GREEN:
        steps.append(("non_green", lambda l: l.pick_track_status("1")))
    steps.append(("compound", lambda l: l[l["Compound"].isin(KEEP_COMPOUNDS)]))

    log = {"Year": year, "Round": rnd, "Circuit": circuit, "all_laps": len(laps)}
    current = laps
    for label, fn in steps:
        before = len(current)
        current = fn(current)
        log[label] = before - len(current)      # laps removed at this step
    log["final"] = len(current)

    clean = pd.DataFrame(current).copy()
    clean["LapSeconds"] = clean["LapTime"].dt.total_seconds()
    clean["Year"] = year
    clean["Round"] = rnd
    clean["Circuit"] = circuit
    return clean[COLUMNS], log


races = list_races()
print(f"{len(races)} races found from {START_YEAR} to {END_YEAR}")

frames, logs, skipped = [], [], []
fails_in_a_row = 0
stopped_early = False

for i, (year, rnd, circuit) in enumerate(races, 1):
    data_path = f"race_parts/{year}_{rnd}_laps.csv"
    log_path = f"race_parts/{year}_{rnd}_log.csv"

    # Already finished on an earlier run: reuse it, no download needed
    if os.path.exists(data_path) and os.path.exists(log_path):
        frames.append(pd.read_csv(data_path))
        logs.append(pd.read_csv(log_path).iloc[0].to_dict())
        continue

    print(f"[{i}/{len(races)}] {year} round {rnd} {circuit}")
    try:
        clean, log = get_clean_laps(year, rnd, circuit)
    except Exception as e:
        print(f"   SKIPPED: {e}")
        skipped.append((year, rnd, circuit, str(e)))
        fails_in_a_row += 1
        if fails_in_a_row >= MAX_FAILURES_IN_A_ROW:
            print(f"\nStopping: {MAX_FAILURES_IN_A_ROW} downloads failed in a row.")
            print("Finished races are saved in race_parts/. Wait a while, then run "
                  "this script again and it will continue where it stopped.")
            stopped_early = True
            break
        continue

    fails_in_a_row = 0
    clean.to_csv(data_path, index=False)
    pd.DataFrame([log]).to_csv(log_path, index=False)
    frames.append(clean)
    logs.append(log)
    time.sleep(PAUSE_SECONDS)

if not frames:
    raise SystemExit("No races were loaded, so there is nothing to save.")

data = pd.concat(frames, ignore_index=True)
log_df = pd.DataFrame(logs)
print(f"\nRaces loaded so far: {len(log_df)} of {len(races)}")

# ---- Removal summary ----
step_cols = [c for c in log_df.columns
             if c not in ("Year", "Round", "Circuit", "all_laps", "final")]

print("\nPercent of laps removed, by season:")
by_year = log_df.groupby("Year")[["all_laps"] + step_cols + ["final"]].sum()
pct_year = by_year[step_cols].div(by_year["all_laps"], axis=0) * 100
pct_year["total_removed"] = 100 - by_year["final"] / by_year["all_laps"] * 100
print(pct_year.round(1).to_string())

totals = log_df[["all_laps"] + step_cols + ["final"]].sum()
print("\nOverall:")
for c in step_cols:
    print(f"  {c}: {totals[c]} laps ({totals[c] / totals['all_laps'] * 100:.1f}%)")
print(f"  total removed: {totals['all_laps'] - totals['final']} of {totals['all_laps']} "
      f"({(1 - totals['final'] / totals['all_laps']) * 100:.1f}%)")

# Races that lose a lot of laps (wet races, red flags, safety cars)
log_df["pct_removed"] = (1 - log_df["final"] / log_df["all_laps"]) * 100
print("\nRaces with the highest share of laps removed:")
print(log_df.sort_values("pct_removed", ascending=False)
      [["Year", "Round", "Circuit", "all_laps", "final", "pct_removed"]]
      .head(8).round(1).to_string(index=False))

# What dropna() will remove in the modelling script
key = ["TyreLife", "FreshTyre", "TrackTemp", "AirTemp", "LapSeconds"]
print("\nMissing values in key columns:")
print(data[key].isna().sum())
print("Rows before dropna:", len(data), "| after:", len(data.dropna(subset=key)))

print("\nClean laps per season:")
print(data.groupby("Year").size())

if skipped:
    print("\nSKIPPED races:")
    for s in skipped:
        print("  ", s)

data.to_csv("laps_sample.csv", index=False)
log_df.to_csv("removal_log.csv", index=False)
print("\nSaved laps_sample.csv and removal_log.csv")
if stopped_early:
    print("NOTE: the run stopped early, so these files are incomplete. Run again later.")