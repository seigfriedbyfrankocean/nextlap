"""Replay a held-out race with the same circuit-median predictor used live."""
import argparse
from pathlib import Path

import pandas as pd

from predict_next_lap import DEFAULT_DATA, fit_baseline, predict_next_lap


def replay(year, round_number, dataset_path=DEFAULT_DATA, output_path=None):
    data = pd.read_csv(dataset_path)
    training_rows = data[data["Year"] < year]
    race = data[(data["Year"] == year) & (data["Round"] == round_number)].copy()
    if training_rows.empty:
        raise ValueError(f"No training rows exist before {year}.")
    if race.empty:
        raise ValueError(f"No prediction rows found for {year} Round {round_number}.")

    baseline = fit_baseline(dataset_path, before_year=year)
    rows = []
    for row in race.itertuples(index=False):
        predicted, delta, source, sample_count = predict_next_lap(
            row.Circuit, row.LapSeconds, baseline
        )
        rows.append({
            "Year": row.Year,
            "Round": row.Round,
            "Circuit": row.Circuit,
            "Driver": row.Driver,
            "LapNumber": row.LapNumber,
            "LapSeconds": row.LapSeconds,
            "ActualNextLapSeconds": row.NextLapSeconds,
            "PredictedNextLapSeconds": predicted,
            "AbsErrorSeconds": abs(row.NextLapSeconds - predicted),
            "PersistenceAbsErrorSeconds": abs(row.NextLapSeconds - row.LapSeconds),
            "BaselineDeltaSeconds": delta,
            "BaselineSource": source,
            "BaselineTrainingRows": sample_count,
        })

    result = pd.DataFrame(rows).sort_values(["Driver", "LapNumber"])
    print(f"Race: {year} Round {round_number} — {race.iloc[0]['Circuit']}")
    print(f"Training: seasons before {year} ({len(training_rows):,} rows)")
    print(f"Replayed predictions: {len(result):,}")
    print(f"Circuit-median MAE: {result['AbsErrorSeconds'].mean():.3f} s")
    print(f"Persistence MAE: {result['PersistenceAbsErrorSeconds'].mean():.3f} s")
    print("\nSample predictions:")
    print(result[[
        "Driver", "LapNumber", "LapSeconds", "PredictedNextLapSeconds",
        "ActualNextLapSeconds", "AbsErrorSeconds",
    ]].head(12).to_string(index=False, formatters={
        "LapSeconds": "{:.3f}".format,
        "PredictedNextLapSeconds": "{:.3f}".format,
        "ActualNextLapSeconds": "{:.3f}".format,
        "AbsErrorSeconds": "{:.3f}".format,
    }))
    if output_path is not None:
        output_path = Path(output_path)
        result.to_csv(output_path, index=False)
        print(f"\nSaved per-lap replay: {output_path}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--round", dest="round_number", type=int, default=8)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--output", type=Path, help="Optional path for per-lap predictions")
    args = parser.parse_args()
    replay(args.year, args.round_number, args.data, args.output)


if __name__ == "__main__":
    main()