import pandas as pd

df = pd.read_csv("laps_sample.csv")
race = ["Year", "Round", "Circuit"]

print("Shape:", df.shape)
print("Columns:", list(df.columns))
print("\nFirst rows:")
print(df.head(3).to_string())

print("\nMissing values per column:")
print(df.isna().sum().to_string())

per_race = df.groupby(race).size()
print(f"\nRaces in file: {len(per_race)}")
print("Laps per race (min / median / max):",
      per_race.min(), "/", int(per_race.median()), "/", per_race.max())
print("\nFewest laps:")
print(per_race.sort_values().head(5).to_string())

print("\nNumeric summary:")
print(df.describe().T.round(2).to_string())

print("\nCompound counts:")
print(df["Compound"].value_counts().to_string())
for col in ("Rainfall", "InSafetyCar", "FreshTyre"):
    if col in df.columns:
        print(f"\n{col} counts:")
        print(df[col].value_counts(dropna=False).to_string())


def check(name, mask):
    n = int(mask.sum())
    print(f"  {name}: {'OK' if n == 0 else str(n) + ' rows'}")


print("\nSanity checks (OK means no problem rows found):")
check("lap time outside 50-200 s", ~df["LapSeconds"].between(50, 200))
check("TyreLife below 1", df["TyreLife"] < 1)
check("lap 1 still present (should be removed)", df["LapNumber"] < 2)
check("duplicate laps", df.duplicated(["Year", "Round", "Driver", "LapNumber"]))
check("track temp outside 10-70", ~df["TrackTemp"].between(10, 70))
check("air temp outside 0-50", ~df["AirTemp"].between(0, 50))

# Within a stint, tyre age must rise by exactly as many laps as the lap number does
ordered = df.sort_values(["Year", "Round", "Driver", "Stint", "LapNumber"])
grp = ordered.groupby(["Year", "Round", "Driver", "Stint"])
tyre_step = grp["TyreLife"].diff()
lap_step = grp["LapNumber"].diff()
check("TyreLife step differs from LapNumber step within a stint",
      tyre_step.notna() & (tyre_step != lap_step))

if "NextLapNumber" in df.columns:
    check("NextLapNumber is not LapNumber + 1",
          df["NextLapNumber"].notna() & (df["NextLapNumber"] != df["LapNumber"] + 1))
    print(f"  rows with no next lap: {int(df['NextLapNumber'].isna().sum())}")