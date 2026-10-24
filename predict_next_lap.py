"""Predict the next lap with persistence or an optional circuit-median adjustment."""
import argparse
import math
from pathlib import Path

import pandas as pd

DEFAULT_DATA = Path(__file__).resolve().with_name("laps_sample_v3.csv")


def fit_baseline(dataset_path=DEFAULT_DATA, before_year=None):
    """Fit circuit median lap-to-lap deltas, optionally using earlier seasons only."""
    data = pd.read_csv(
        dataset_path,
        usecols=["Year", "Circuit", "LapSeconds", "NextLapSeconds"],
    )
    if before_year is not None:
        data = data[data["Year"] < before_year]
    data = data.dropna(subset=["Circuit", "LapSeconds", "NextLapSeconds"])
    data["Circuit"] = data["Circuit"].astype(str).str.strip()
    data["DeltaSeconds"] = data["NextLapSeconds"] - data["LapSeconds"]

    by_circuit = data.groupby("Circuit")["DeltaSeconds"].agg(["median", "count"])
    global_delta = float(data["DeltaSeconds"].median())
    return by_circuit, global_delta, len(data)


def predict_next_lap(circuit, current_lap_seconds, baseline=None):
    """Return (predicted_seconds, delta_seconds, source, sample_count)."""
    current = float(current_lap_seconds)
    if not math.isfinite(current) or current <= 0:
        raise ValueError("current_lap_seconds must be a positive finite number")

    if baseline is None:
        return current, 0.0, "persistence", 0
    by_circuit, global_delta, global_count = baseline

    name = str(circuit).strip()
    match = {str(key).casefold(): key for key in by_circuit.index}
    key = match.get(name.casefold())
    if key is None:
        delta = global_delta
        source = "overall median (unseen circuit)"
        count = global_count
    else:
        delta = float(by_circuit.loc[key, "median"])
        source = f"{key} median"
        count = int(by_circuit.loc[key, "count"])

    return current + delta, delta, source, count


def main():
    parser = argparse.ArgumentParser(
        description="Predict the next lap with persistence or a circuit-median adjustment."
    )
    parser.add_argument("circuit", help="Circuit name as listed in laps_sample_v3.csv")
    parser.add_argument("current_lap_seconds", type=float, help="Current lap time in seconds")
    parser.add_argument(
        "--method", choices=("persistence", "circuit"), default="persistence",
        help="Persistence is the default; circuit uses a median adjustment.",
    )
    parser.add_argument(
        "--data", type=Path, default=DEFAULT_DATA,
        help=f"Training dataset for --method circuit (default: {DEFAULT_DATA.name})",
    )
    args = parser.parse_args()

    baseline = fit_baseline(args.data) if args.method == "circuit" else None
    predicted, delta, source, count = predict_next_lap(
        args.circuit, args.current_lap_seconds, baseline
    )
    print(f"Circuit: {args.circuit}")
    print(f"Current lap: {args.current_lap_seconds:.3f} s")
    print(f"Predicted next lap: {predicted:.3f} s")
    details = f" ({count} training rows)" if count else ""
    print(f"Adjustment: {delta:+.3f} s ({source}{details})")


if __name__ == "__main__":
    main()