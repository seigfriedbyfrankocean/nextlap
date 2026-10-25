
import pandas as pd

df = pd.read_csv("laps_sample.csv")

race = ["Year", "Round"]
driver_race = ["Year", "Round", "Driver"]
lap_key = driver_race + ["LapNumber"]

df["DeltaSeconds"] = df["NextLapSeconds"] - df["LapSeconds"]

print("\n=== BASIC INTEGRITY ===")
print(f"Rows: {len(df):,}")
print(f"Races: {df[race].drop_duplicates().shape[0]}")
print(f"Duplicate driver/race/lap keys: {df.duplicated(lap_key).sum()}")
print(f"Missing values: {df.isna().sum().sum()}")

print("\n=== TARGET ALIGNMENT ===")
gap = df["NextLapNumber"] - df["LapNumber"]
print("Target lap gap counts:")
print(gap.value_counts(dropna=False).sort_index().to_string())
print(f"Targets not exactly one lap ahead: {(gap != 1).sum()}")

print("\n=== TYRE STINT CONSISTENCY ===")
stint_key = driver_race + ["Stint"]
s = df.sort_values(stint_key + ["LapNumber"]).copy()

lap_diff = s.groupby(stint_key)["LapNumber"].diff()
age_diff = s.groupby(stint_key)["TyreLife"].diff()
bad_age = age_diff.notna() & (
    (age_diff - lap_diff).abs() > 0.01
)

print(f"Within-stint tyre-age inconsistencies: {bad_age.sum()}")
if bad_age.any():
    cols = stint_key + [
        "LapNumber", "Compound", "TyreLife", "LapSeconds"
    ]
    print(s.loc[bad_age, cols].head(25).to_string(index=False))

print("\n=== LARGE LAP-TIME CHANGES ===")
for threshold in [3, 5, 8, 10]:
    print(
        f"|next lap - current lap| > {threshold}s: "
        f"{(df['DeltaSeconds'].abs() > threshold).sum()}"
    )

cols = driver_race + [
    "Circuit", "LapNumber", "NextLapNumber", "Compound",
    "TyreLife", "LapSeconds", "NextLapSeconds", "DeltaSeconds"
]
outliers = df.loc[df["DeltaSeconds"].abs() > 5, cols].copy()
outliers["AbsDelta"] = outliers["DeltaSeconds"].abs()
print("\nLargest 25 changes:")
print(
    outliers.sort_values("AbsDelta", ascending=False)
    .head(25)[cols]
    .to_string(index=False)
)

print("\n=== RACE-WIDE ANOMALIES ===")
# Counts how many drivers have a >5s change on the same lap transition.
df["LargeChange"] = df["DeltaSeconds"].abs() > 5
summary = (
    df.groupby(["Year", "Round", "Circuit", "LapNumber"])
    .agg(
        drivers=("Driver", "nunique"),
        large_changes=("LargeChange", "sum"),
    )
    .reset_index()
)
summary = summary[
    (summary["large_changes"] >= 3)
    & (summary["large_changes"] / summary["drivers"] >= 0.2)
]
print(
    summary.sort_values(
        ["large_changes", "drivers"], ascending=False
    ).head(30).to_string(index=False)
)
