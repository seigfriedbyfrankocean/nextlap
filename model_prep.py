import pandas as pd

data = pd.read_csv("laps_sample.csv")

keep = ["Driver", "Team", "Year", "Circuit", "Compound", "TyreLife",
        "FreshTyre", "LapNumber", "TrackTemp", "AirTemp", "LapSeconds"]
df = data[keep].dropna()
print(df.shape)
print(df.groupby("Circuit")[["TrackTemp", "AirTemp"]].agg(["min", "max"]))

# Temporary split, only to test the pipeline: the last 20% of laps in each race become the test set
cut = df.groupby("Circuit")["LapNumber"].transform(lambda s: s.quantile(0.8))
train = df[df["LapNumber"] <= cut]
test = df[df["LapNumber"] > cut].copy()

# Baseline: the driver's median lap time at that circuit, from the training laps
baseline = train.groupby(["Circuit", "Driver"])["LapSeconds"].median()
test["Pred"] = [baseline.get((c, d)) for c, d in zip(test["Circuit"], test["Driver"])]
test = test.dropna(subset=["Pred"])

mae = (test["LapSeconds"] - test["Pred"]).abs().mean()
print("Baseline MAE:", round(mae, 3), "seconds")