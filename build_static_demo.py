"""Build static historical replay files for the Cloudflare Pages portfolio demo."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import local_app

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "web" / "demo-data"
RACE_OUTPUT = OUTPUT / "races"
ROW_COLUMNS = [
    "LapNumber",
    "CurrentLapSeconds",
    "ActualNextLapSeconds",
    "PersistencePrediction",
    "PersistenceAbsError",
    "CircuitPrediction",
    "CircuitAbsError",
    "MLPrediction",
    "MLAbsError",
    "MLTrainingRows",
    "TyreLife",
]


def json_value(value):
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float):
        return round(value, 4)
    return value


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def main():
    print("Preparing historical replay predictions from the project dataset...", flush=True)
    replay = local_app._build_replay_cache(pd)
    replay = replay.dropna(subset=["Year", "Round", "Circuit", "Driver", "LapNumber"]).copy()
    replay["Year"] = pd.to_numeric(replay["Year"], errors="coerce").astype("Int64")
    replay["Round"] = pd.to_numeric(replay["Round"], errors="coerce").astype("Int64")
    replay["Driver"] = replay["Driver"].astype(str).str.upper()

    years = sorted(int(value) for value in replay["Year"].dropna().unique())
    index = {"years": years, "default_year": years[-1], "default_round": 4, "seasons": {}}
    available_rounds = set(
        int(value)
        for value in replay.loc[replay["Year"] == index["default_year"], "Round"].dropna().unique()
    )
    if index["default_round"] not in available_rounds:
        index["default_round"] = max(available_rounds)

    for year in years:
        season = replay[replay["Year"] == year]
        races = season[["Round", "Circuit"]].drop_duplicates().sort_values("Round")
        season_index = {"races": [], "rounds": {}}
        for race_row in races.itertuples(index=False):
            round_number = int(race_row.Round)
            circuit = str(race_row.Circuit)
            race = season[season["Round"] == round_number]
            driver_rows = race[["Driver", "Team"]].copy()
            driver_rows["Driver"] = driver_rows["Driver"].astype(str).str.upper()
            driver_rows = driver_rows.drop_duplicates("Driver").set_index("Driver")
            drivers = [
                local_app.replay_driver_data(code, year, str(driver_rows.loc[code, "Team"]))
                for code in sorted(driver_rows.index)
            ]
            race_entry = {
                "round": round_number,
                "circuit": circuit,
                "country_code": local_app.RACE_COUNTRY_CODES.get(circuit.strip().casefold(), ""),
                "circuit_svg": local_app.circuit_svg_url(circuit),
            }
            has_ml = bool(race.get("MLPrediction", pd.Series(dtype=float)).notna().any())
            training_rows = int(race["MLTrainingRows"].max()) if "MLTrainingRows" in race and race["MLTrainingRows"].notna().any() else 0
            season_index["races"].append(race_entry)
            season_index["rounds"][str(round_number)] = {
                "drivers": drivers,
                "has_ml_model": has_ml,
                "ml_training_rows": training_rows,
                "default_driver": "VER" if any(item["acronym"] == "VER" for item in drivers) else (drivers[0]["acronym"] if drivers else ""),
            }

            driver_payloads = {}
            for code, selected in race.groupby("Driver", sort=True):
                selected = selected.sort_values("LapNumber")
                available_columns = [column for column in ROW_COLUMNS if column in selected.columns]
                rows = [
                    {column: json_value(row[column]) for column in available_columns}
                    for _, row in selected[available_columns].iterrows()
                ]
                ml_errors = selected["MLAbsError"].dropna() if "MLAbsError" in selected else pd.Series(dtype=float)
                metrics = {
                    "persistence_mae": json_value(selected["PersistenceAbsError"].mean()),
                    "circuit_mae": json_value(selected["CircuitAbsError"].mean()),
                    "ml_mae": json_value(ml_errors.mean()) if not ml_errors.empty else None,
                    "ml_prediction_rows": int(selected["MLPrediction"].notna().sum()) if "MLPrediction" in selected else 0,
                    "laps": int(len(selected)),
                }
                driver_payloads[str(code).upper()] = {"rows": rows, "metrics": metrics}

            write_json(
                RACE_OUTPUT / f"{year}-{round_number}.json",
                {"year": year, "round": round_number, "circuit": circuit,
                 "circuit_svg": local_app.circuit_svg_url(circuit), "drivers": driver_payloads},
            )
        index["seasons"][str(year)] = season_index

    write_json(OUTPUT / "index.json", index)
    file_count = len(list(RACE_OUTPUT.glob("*.json")))
    total_bytes = sum(path.stat().st_size for path in OUTPUT.rglob("*.json"))
    print(f"Wrote {file_count} race files for seasons {years} ({total_bytes:,} bytes).", flush=True)
    print(f"Default replay: {index['default_year']} Round {index['default_round']}.", flush=True)


if __name__ == "__main__":
    main()
