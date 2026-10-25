
import pandas as pd

df = pd.read_csv("laps_sample.csv")

# Sort within each race and driver.
df = df.sort_values(
    ["Year", "Round", "Driver", "LapNumber"]
).copy()

# Check whether each target is actually the next numbered lap.
df["NextLapNumberExpected"] = df["LapNumber"] + 1

if "NextLapNumber" in df.columns:
    df["TargetGap"] = (
        df["NextLapNumber"] - df["NextLapNumberExpected"]
    )

    print("=== Target lap-number alignment ===")
    print("Rows:", len(df))
    print("Missing target lap numbers:", df["NextLapNumber"].isna().sum())
    print("Correct next-lap targets:", (df["TargetGap"] == 0).sum())
    print("Unexpected target gaps:", (df["TargetGap"] != 0).sum())

    print("\nExamples of unexpected gaps:")
    print(
        df.loc[
            df["TargetGap"].notna() & (df["TargetGap"] != 0),
            [
                "Year", "Round", "Circuit", "Driver",
                "LapNumber", "NextLapNumber",
                "LapSeconds", "NextLapSeconds",
            ],
        ].head(20).to_string(index=False)
    )
else:
    print("No NextLapNumber column found; cannot directly verify target lap numbers.")

# Check for duplicate driver/lap observations within a race.
keys = ["Year", "Round", "Driver", "LapNumber"]
duplicates = df.duplicated(keys, keep=False)

print("\n=== Duplicate observations ===")
print("Duplicate rows:", duplicates.sum())

if duplicates.any():
    print(df.loc[duplicates, keys].head(20).to_string(index=False))

# Check for impossible or suspicious lap-time values.
print("\n=== Lap-time sanity checks ===")
for col in ["LapSeconds", "NextLapSeconds"]:
    if col in df.columns:
        print(f"\n{col}:")
        print(df[col].describe(percentiles=[0.01, 0.5, 0.99]))

# Inspect the available columns to help audit pit-stop filtering.
print("\n=== Available columns ===")
print(", ".join(df.columns))
