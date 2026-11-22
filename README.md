# NextLap

NextLap forecasts a Formula 1 driver's next lap time. The local dashboard can watch a live race through OpenF1. The hosted site replays completed races and compares forecasts with actual lap times.

The live monitor uses the latest completed lap as a persistence forecast. Historical replay also shows circuit-median and machine-learning estimates. The replay model uses lap, tyre, and weather features from earlier races.

## What it includes

- Live race monitoring in the local Python app
- Historical race replay in the local app and hosted demo
- Persistence, circuit-median, and machine-learning forecasts for comparison
- A forecast log that matches predictions with the next completed lap

## Stack

- Python, pandas, and scikit-learn for data processing and model evaluation
- OpenF1 for race data
- HTML, CSS, and JavaScript for the dashboard
- Cloudflare Pages for the hosted replay demo

## Run locally

From the repository root, create and activate a virtual environment, then install the dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Start the dashboard:

```powershell
python local_app.py
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). Press `Ctrl+C` in the terminal to stop it.

The live monitor needs OpenF1 live-data access. Historical replay works from the dataset included in the repository.

## Refresh race replay data

Build the historical dataset and its static replay files with:

```powershell
python build_dataset_openf1_v3.py
python build_static_demo.py
```

GitHub Actions runs this refresh on Monday evenings and can also be started manually from the Actions tab. A successful run commits the updated replay files to the default branch; the hosted site then redeploys through its Git connection.

## Model evaluation

The figures below come from an earlier dataset and have not been rerun on the current v3 data. Lower MAE is better.

| Approach | Held-out races MAE (s) | 2026 held-out season MAE (s) |
|---|---:|---:|
| Persistence baseline | 0.409 | 0.486 |
| Circuit baseline | **0.408** | **0.485** |
| Recent-pace baseline | 0.425 | 0.500 |
| Ridge regression | 0.441 | 0.554 |
| HistGradientBoosting | 0.541 | 0.793 |

In those runs, neither fitted model beat the circuit baseline. Treat the results as historical until the v3 data is validated and the evaluation is rerun.

## Project layout

| Path | Purpose |
|---|---|
| `local_app.py` | Local dashboard server |
| `predict_live.py` | Live-session data handling and forecasts |
| `predict_next_lap.py` | Persistence and circuit-median forecast helpers |
| `build_dataset_openf1_v3.py` | Validated OpenF1 dataset builder |
| `build_static_demo.py` | Generates replay JSON for the hosted site |
| `analysis/` | Offline model fitting, race replay, and tyre analysis |
| `web/` | Dashboard frontend and static replay data |
| `laps_sample_v3.csv` | Historical lap dataset |
| `replay_2026_holdout.csv` | Holdout dataset for evaluation |

Run analysis modules from the repository root, for example:

```powershell
python -m analysis.replay_backtest --year 2026 --round 8
```

## Contributing

Bug reports, suggestions, and constructive feedback are welcome through [GitHub Issues](https://github.com/seigfriedbyfrankocean/NextLap/issues).

## License

Distributed under the MIT License. See [LICENSE](LICENSE).

## Disclaimer

NextLap is an independent, non-commercial fan project. It is not affiliated with Formula 1, Formula One Management, the FIA, or any Formula 1 team. All related trademarks belong to their respective owners.
