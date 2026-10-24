
import numpy as np
import pandas as pd

from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import (
    OneHotEncoder,
    OrdinalEncoder,
    StandardScaler,
)

TARGET = "DeltaSeconds"

# Categorical features
CAT = ["Driver", "Car", "Circuit", "Compound"]

# Numeric features
TYRE_COLS = [
    "TyreLife",
    "TyreLife_sq",
    "Tyre_SOFT",
    "Tyre_MEDIUM",
    "Tyre_HARD",
]
TEMP_COLS = ["TrackTemp", "AirTemp"]
NUM = TYRE_COLS + TEMP_COLS + ["FreshTyre", "LapSeconds"]


# ---- Load data and build features ----
DATA_PATH = "laps_sample_v3.csv"
data = pd.read_csv(DATA_PATH)

data["Car"] = (
    data["Team"].astype(str) + " " + data["Year"].astype(str)
)

needed = [
    "Year", "Round", "Driver", "Team", "Circuit",
    "Compound", "TyreLife", "LapNumber",
    "TrackTemp", "AirTemp", "FreshTyre",
    "LapSeconds", "NextLapSeconds",
]

df = data.dropna(subset=needed).copy()

df["DeltaSeconds"] = df["NextLapSeconds"] - df["LapSeconds"]

# Sort chronologically within each race and driver.
df = df.sort_values(
    ["Year", "Round", "Driver", "LapNumber"]
).copy()

# ---- Recent-pace baseline ----
groups = df.groupby(
    ["Year", "Round", "Driver"],
    sort=False,
)

df["Prev1"] = groups["LapSeconds"].shift(1)
df["Prev1Lap"] = groups["LapNumber"].shift(1)

df["Prev2"] = groups["LapSeconds"].shift(2)
df["Prev2Lap"] = groups["LapNumber"].shift(2)

# Only use previous laps when the lap numbers are consecutive.
df.loc[
    df["LapNumber"] - df["Prev1Lap"] != 1, "Prev1"
] = np.nan

df.loc[
    df["LapNumber"] - df["Prev2Lap"] != 2, "Prev2"
] = np.nan

# Average the current lap and up to two previous consecutive laps.
df["RecentPace"] = df[
    ["LapSeconds", "Prev1", "Prev2"]
].mean(axis=1)

df["FreshTyre"] = df["FreshTyre"].astype(int)

# Unique race identifier.
df["Race"] = (
    df["Year"].astype(str) + "_" + df["Round"].astype(str)
)

# Tyre wear features.
df["TyreLife_sq"] = df["TyreLife"] ** 2

for compound in ("SOFT", "MEDIUM", "HARD"):
    df[f"Tyre_{compound}"] = np.where(
        df["Compound"] == compound,
        df["TyreLife"],
        0.0,
    )

df = df.reset_index(drop=True)

print("Rows before dropna:", len(data), "| after:", len(df))
print(
    "Races:", df["Race"].nunique(),
    "| Seasons:", sorted(df["Year"].unique()),
)


# ---- Models ----
def make_model(kind, cat, num):
    if kind == "ridge":
        pre = ColumnTransformer([
            (
                "cat",
                OneHotEncoder(
                    handle_unknown="ignore",
                    sparse_output=False,
                ),
                cat,
            ),
            ("num", StandardScaler(), num),
        ])

        estimator = Ridge(alpha=1.0)

    else:
        pre = ColumnTransformer([
            (
                "cat",
                OrdinalEncoder(
                    handle_unknown="use_encoded_value",
                    unknown_value=-1,
                ),
                cat,
            ),
            ("num", "passthrough", num),
        ])

        estimator = HistGradientBoostingRegressor(
            max_iter=300,
            learning_rate=0.05,
            random_state=0,
            categorical_features=(
                [True] * len(cat) + [False] * len(num)
            ),
        )

    return make_pipeline(pre, estimator)


# ---- Evaluation ----
def abs_errors(kind, cat, num, train, test):
    """Absolute next-lap prediction errors, measured in seconds."""

    # Keep the comparison consistent with the existing evaluation.
    test = test[
        test["Circuit"].isin(train["Circuit"].unique())
    ]

    if test.empty:
        return pd.Series(dtype=float)

    if kind == "persistence":
        # Predict that the next lap matches the current lap.
        pred = test["LapSeconds"]

    elif kind == "recent":
        # Predict using current and recent consecutive lap times.
        pred = test["RecentPace"]

    elif kind == "baseline":
        # Predict a typical lap-to-lap change for this circuit.
        circuit_delta = train.groupby("Circuit")[TARGET].median()
        delta = test["Circuit"].map(circuit_delta)
        pred = test["LapSeconds"] + delta

    else:
        model = make_model(kind, cat, num)
        model.fit(train[cat + num], train[TARGET])

        predicted_delta = model.predict(test[cat + num])
        pred = test["LapSeconds"] + predicted_delta

    return (test["NextLapSeconds"] - pred).abs()


def cv_mae(kind, cat=CAT, num=NUM):
    """Hold out complete races in each cross-validation fold."""

    n_splits = min(5, df["Race"].nunique())

    folds = GroupKFold(n_splits=n_splits).split(
        df,
        groups=df["Race"],
    )

    errors = [
        abs_errors(kind, cat, num, df.iloc[train_idx], df.iloc[test_idx])
        for train_idx, test_idx in folds
    ]

    errors = [e for e in errors if not e.empty]

    return pd.concat(errors).mean()


# ---- 1. Cross-validation ----
print("\n=== Cross-validation (whole races held out) ===")

methods = ("persistence", "recent", "baseline", "ridge", "hgb")

scores = {
    method: cv_mae(method)
    for method in methods
}

for method, score in scores.items():
    print(f"{method:>11} MAE: {score:.3f} s")

# Choose the better ML model for feature ablations.
best = min(("ridge", "hgb"), key=lambda method: scores[method])


# ---- 2. Feature ablations ----
print(f"\nAblations ({best}), CV MAE when features are removed:")

no_tyre = [c for c in NUM if c not in TYRE_COLS]

no_compound_terms = [
    c for c in NUM
    if c not in ("Tyre_SOFT", "Tyre_MEDIUM", "Tyre_HARD")
]

drops = {
    "TyreLife (all)": (CAT, no_tyre),
    "Temps": (
        CAT,
        [c for c in NUM if c not in TEMP_COLS],
    ),
    "Compound": (
        [c for c in CAT if c != "Compound"],
        no_compound_terms,
    ),
    "Driver+Car": (
        [c for c in CAT if c not in ("Driver", "Car")],
        NUM,
    ),
}

for name, (cat, num) in drops.items():
    print(f"  without {name:<15} {cv_mae(best, cat, num):.3f} s")


# ---- 3. Train on earlier seasons, test on latest season ----
last = df["Year"].max()

if df["Year"].nunique() < 2:
    print("\nSkipping season holdout: only one season available.")

else:
    train = df[df["Year"] < last]
    test = df[df["Year"] == last]

    print(f"\n=== Train before {last}, test on {last} ===")
    print("Only circuits represented in the training seasons are evaluated.")

    for method in methods:
        errors = abs_errors(method, CAT, NUM, train, test)

        if errors.empty:
            print(f"{method:>11} MAE: no eligible test rows")
        else:
            print(f"{method:>11} MAE: {errors.mean():.3f} s")
