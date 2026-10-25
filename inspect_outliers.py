
import pandas as pd

df = pd.read_csv("laps_sample.csv")

df["DeltaSeconds"] = df["NextLapSeconds"] - df["LapSeconds"]

race_driver = ["Year", "Round", "Driver"]
df = df.sort_values(race_driver + ["LapNumber"]).copy()

print("=== Size of lap-to-lap changes ===")
for threshold in [1, 2, 3, 5, 10]:
    count = (df["DeltaSeconds"].abs() > threshold).sum()
    print(f"|Delta| > {threshold:2d}s: {count:5d} rows")

print("\n=== 20 largest absolute changes ===")
cols = [
    "Year", "Round", "Circuit", "Driver",
    "LapNumber", "NextLapNumber",
    "LapSeconds", "NextLapSeconds", "DeltaSeconds",
    "Compound", "TyreLife", "Stint",
    "InSafetyCar", "Rainfall",
]

cols = [c for c in cols if c in df.columns]

print(
    df.loc[df["DeltaSeconds"].abs().nlargest(20).index, cols]
    .sort_values("DeltaSeconds", key=abs, ascending=False)
    .to_string(index=False)
)

print("\n=== Largest changes by season ===")
df["AbsDelta"] = df["DeltaSeconds"].abs()

print(
    df.groupby("Year")["AbsDelta"]
    .agg(
        rows="count",
        median="median",
        p99=lambda s: s.quantile(0.99),
        max="max",
    )
    .round(3)
    .to_string()
)
