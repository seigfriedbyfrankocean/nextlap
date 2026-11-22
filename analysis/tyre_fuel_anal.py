import os
import numpy as np
import pandas as pd

BOOTSTRAP_REPEATS = 500          # how many times to resample races for uncertainty
SEED = 0
COMPOUNDS = ["SOFT", "MEDIUM", "HARD"]
STINT_LAPS = 20                  # example stint length used in the plain-English lines

# Columns of the regression, in a fixed order (the code below relies on it)
XCOLS = ["LapNumber",
         "TyreLife_SOFT", "TyreLife_MEDIUM", "TyreLife_HARD",
         "Compound_MEDIUM", "Compound_HARD",
         "TrackTemp"]
TYRE_IDX = [1, 2, 3, 4, 5]       # tyre slopes and compound offsets
PROGRESS_IDX = 0
TEMP_IDX = 6


# ---------------------------------------------------------------------------
# 0. How much did the cleaning remove? (needs removal_log.csv from the builder)
# ---------------------------------------------------------------------------
def removal_overview():
    if not os.path.exists("removal_log.csv"):
        return
    try:
        log = pd.read_csv("removal_log.csv")
        excluded = log["excluded"].fillna("")
        kept = log[excluded == ""]
        raw_all = log["raw_laps"].sum()
        raw_kept = kept["raw_laps"].sum()
        rows = kept["prediction_rows"].sum()
        print("=== Cleaning overview (from removal_log.csv) ===")
        print(f"Races processed: {len(log)} | kept: {len(kept)} | excluded: {len(log) - len(kept)}")
        print(f"Raw laps in all races:         {raw_all}")
        print(f"Raw laps in the kept races:    {raw_kept}")
        print(f"Laps in the final dataset:     {rows}")
        print(f"Removed inside kept races:     {100 * (1 - rows / raw_kept):.1f}%")
        print(f"Not in dataset, all races:     {100 * (1 - rows / raw_all):.1f}%")
        print()
    except Exception as e:                      # never let this stop the analysis
        print(f"(Could not summarise removal_log.csv: {e})\n")


removal_overview()

# ---------------------------------------------------------------------------
# 1. Load and prepare
# ---------------------------------------------------------------------------
data = pd.read_csv("laps_sample.csv")
need = ["Driver", "Year", "Circuit", "Compound", "TyreLife",
        "LapNumber", "TrackTemp", "LapSeconds", "Stint"]
d = data.dropna(subset=need).copy()
d = d[d["Compound"].isin(COMPOUNDS)]
d["Race"] = d["Year"].astype(str) + " " + d["Circuit"]
d["RD"] = d["Race"] + " | " + d["Driver"].astype(str)     # one driver in one race
d = d.sort_values(["RD", "LapNumber"]).reset_index(drop=True)

for c in COMPOUNDS:
    d[f"TyreLife_{c}"] = np.where(d["Compound"] == c, d["TyreLife"], 0.0)
d["Compound_MEDIUM"] = (d["Compound"] == "MEDIUM").astype(float)
d["Compound_HARD"] = (d["Compound"] == "HARD").astype(float)

X = d[XCOLS].astype(float)
y = d["LapSeconds"].astype(float)

# "Within" transformation: subtract each driver-in-a-race's own average.
# This removes the car, the driver, the circuit and that day's conditions, so
# only changes WITHIN one driver's race are used to estimate the effects.
Xd = (X - X.groupby(d["RD"]).transform("mean")).to_numpy()
yd = (y - y.groupby(d["RD"]).transform("mean")).to_numpy()

races = d["Race"].unique()
R, K = len(races), len(XCOLS)
rows_of = d.groupby("Race").indices
XtX = np.stack([Xd[rows_of[r]].T @ Xd[rows_of[r]] for r in races])
Xty = np.stack([Xd[rows_of[r]].T @ yd[rows_of[r]] for r in races])


def fit(weights):
    """Least squares using each race `weights[r]` times (1 = normal fit)."""
    A = np.tensordot(weights, XtX, axes=1)
    b = weights @ Xty
    return np.linalg.lstsq(A, b, rcond=None)[0]


# ---------------------------------------------------------------------------
# 2. Pit stops: last clean lap before a stop vs first clean lap after it
# ---------------------------------------------------------------------------
g = d.groupby("RD")
next_stint = g["Stint"].shift(-1)
is_stop = next_stint.notna() & (next_stint != d["Stint"])
# inspect whether pit-stop comparisons skip race laps
d["NextCleanLap"] = g["LapNumber"].shift(-1)

stop_rows = d.loc[is_stop].copy()
stop_rows["NextCleanLap"] = d.loc[is_stop, "NextCleanLap"]
stop_rows["LapGap"] = (
    stop_rows["NextCleanLap"] - stop_rows["LapNumber"]
)

print("\n=== Pit-stop transition diagnostic ===")
print("Transitions:", len(stop_rows))
print("Lap-gap distribution:")
print(stop_rows["LapGap"].value_counts().sort_index().head(15))

print("\nTransitions with consecutive race laps:")
print((stop_rows["LapGap"] == 1).sum())

print("\nExample transitions:")
print(
    stop_rows[
        ["Year", "Circuit", "Driver", "LapNumber",
         "NextCleanLap", "LapGap", "Stint", "TyreLife",
         "Compound", "LapSeconds"]
    ].head(20).to_string(index=False)
)
nxt = g[XCOLS + ["LapSeconds"]].shift(-1)
dX_stop = nxt.loc[is_stop, XCOLS].to_numpy() - d.loc[is_stop, XCOLS].to_numpy()
dy_stop = (nxt.loc[is_stop, "LapSeconds"].to_numpy()
           - d.loc[is_stop, "LapSeconds"].to_numpy())
stop_race = pd.Categorical(d.loc[is_stop, "Race"], categories=races).codes
sum_dX = np.zeros((R, K))
np.add.at(sum_dX, stop_race, dX_stop)
sum_dy = np.bincount(stop_race, weights=dy_stop, minlength=R)
stops_per_race = np.bincount(stop_race, minlength=R).astype(float)


def stop_breakdown(weights, coef):
    n = weights @ stops_per_race
    mean_dX = (weights @ sum_dX) / n
    observed = (weights @ sum_dy) / n
    tyres = mean_dX[TYRE_IDX] @ coef[TYRE_IDX]
    progress = mean_dX[PROGRESS_IDX] * coef[PROGRESS_IDX]
    temp = mean_dX[TEMP_IDX] * coef[TEMP_IDX]
    other = observed - tyres - progress - temp
    return np.array([observed, tyres, progress, temp, other])


# ---------------------------------------------------------------------------
# 3. Estimate, then bootstrap over whole races for uncertainty
# ---------------------------------------------------------------------------
ones = np.ones(R)
coef = fit(ones)
breakdown = stop_breakdown(ones, coef)

rng = np.random.default_rng(SEED)
boot_coef, boot_break = [], []
for _ in range(BOOTSTRAP_REPEATS):
    w = np.bincount(rng.integers(0, R, R), minlength=R).astype(float)
    if (w @ stops_per_race) == 0:
        continue
    c = fit(w)
    boot_coef.append(c)
    boot_break.append(stop_breakdown(w, c))
boot_coef = np.array(boot_coef)
boot_break = np.array(boot_break)


def interval(samples):
    lo, hi = np.percentile(samples, [2.5, 97.5])
    return lo, hi


def line(label, est, samples, unit="s"):
    lo, hi = interval(samples)
    sig = "" if (lo <= 0 <= hi) else "  <- clearly not zero"
    print(f"  {label:<34}{est:>8.3f} {unit}   (95% range {lo:>7.3f} to {hi:>7.3f}){sig}")


# ---------------------------------------------------------------------------
# 4. Report
# ---------------------------------------------------------------------------
print("=== Data used ===")
print(f"Laps: {len(d)} | races: {R} | driver-in-a-race groups: {d['RD'].nunique()} "
      f"| pit stops used: {int(stops_per_race.sum())}")

tyre_total = Xd[:, 1:4].sum(axis=1)
corr = np.corrcoef(Xd[:, PROGRESS_IDX], tyre_total)[0, 1]
print(f"Correlation of lap number with tyre age inside a driver's race: {corr:.2f}")
print("(Close to 1 would mean the two cannot be separated; pit stops are what split them.)")

pred = Xd @ coef
within_r2 = 1 - np.sum((yd - pred) ** 2) / np.sum(yd ** 2)
print(f"Share of within-driver lap-time variation explained: {within_r2:.1%}")

print("\n=== Effects, in seconds, with 95% ranges from resampling whole races ===")
line("Race progress (per lap)", coef[0], boot_coef[:, 0], "s/lap")
for i, name in zip([1, 2, 3], COMPOUNDS):
    line(f"Tyre wear, {name} (per lap of age)", coef[i], boot_coef[:, i], "s/lap")
line("Pace offset, MEDIUM vs SOFT", coef[4], boot_coef[:, 4])
line("Pace offset, HARD vs SOFT", coef[5], boot_coef[:, 5])
line("Track temperature (per degree C)", coef[6], boot_coef[:, 6], "s/degC")

print(f"\n=== In plain terms, over {STINT_LAPS} laps ===")
print(f"  Race progress changes lap time by {coef[0] * STINT_LAPS:+.2f} s "
      f"(negative = faster).")
for i, name in zip([1, 2, 3], COMPOUNDS):
    print(f"  {name} tyre wear changes lap time by {coef[i] * STINT_LAPS:+.2f} s.")

print("\n=== What changes across a pit stop (average per stop) ===")
print("Last clean lap before the stop vs first clean lap after it. Negative = faster.")
labels = ["Observed lap-time change", "  from fresher tyres / compound",
          "  from race progress (fuel etc.)", "  from track temperature",
          "  not explained by the model"]
for k, label in enumerate(labels):
    line(label, breakdown[k], boot_break[:, k])

print("\nCaution: 'race progress' bundles fuel burn with the track getting faster as")
print("rubber builds up, and anything else that changes through a race. This data")
print("cannot separate them, so do not call it 'the fuel effect'.")