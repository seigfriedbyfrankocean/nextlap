 <p align="center">
  <img src="web/assets/icon.png" alt="NextLap logo" width="240">
</p>

# NextLap

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/)

NextLap is a local Formula 1 dashboard for monitoring live race sessions and evaluating next-lap time predictions against historical race data. Built with Python and machine learning, it combines live telemetry, historical replay, and model benchmarking in a single interface.

## Features

- **Live Monitor:** Connects to OpenF1 during live sessions to process incoming telemetry and generate next-lap forecasts.
- **Historical Replay:** Review completed races step by step and compare model predictions with actual lap times.
- **Prediction Benchmarking:** Evaluate a Gradient Boosting model against a circuit-median baseline.
- **Race Context:** Explore session data by season, race, circuit, driver, and team.
- **Interactive Dashboard:** View race information, telemetry, and prediction results through a local web interface.

> **Note:** Historical Replay is intended for evaluating predictions on completed races. It does not generate live forecasts.

## Screenshots

### Live Monitor

Monitor live sessions and view forecasts as new lap data becomes available.

![NextLap Live Monitor](docs/screenshots/live-monitor.png)

### Historical Replay

Inspect completed races and compare predicted lap times with actual results.

![NextLap Historical Replay](docs/screenshots/historical-replay.png)

## Getting Started

### Prerequisites

- Python 3.9 or later
- Git
- An internet connection for accessing OpenF1 data during supported live sessions

### Installation

Clone the repository and navigate to the project directory:

```bash
git clone https://github.com/seigfriedbyfrankocean/NextLap.git
cd NextLap
```

Install the project's dependencies using the dependency file provided in the repository, if available.

### Running Locally

Start the local dashboard server from the repository root:

```powershell
python local_app.py
```

Open the dashboard in your browser:

[http://127.0.0.1:8765](http://127.0.0.1:8765)

To stop the server, press `Ctrl + C` in the terminal.

## Hosted Demo

Try the hosted dashboard at [nextlap.pages.dev](https://nextlap.pages.dev).

The hosted version provides access to pre-rendered historical replay data from the 2023–2026 Formula 1 seasons.

**Limitations:**
- Historical Replay uses precomputed data and does not generate new predictions.
- Live monitoring requires the local Python application and a connection to OpenF1.

### Rebuilding Demo Data

To regenerate the static replay dataset after modifying the model or historical data, run:

```powershell
python build_static_demo.py
```

## Project Structure

| File or Directory | Description |
|---|---|
| `local_app.py` | Local web server and dashboard entry point |
| `web/` | Frontend interface, assets, fonts, and circuit layouts |
| `predict_live.py` | Live telemetry processing and forecast generation |
| `model_fit.py` | Training script for the Gradient Boosting model |
| `build_static_demo.py` | Generates precomputed prediction data for the hosted demo |
| `laps_sample_v3.csv` | Historical lap dataset used for model training and evaluation |
| `replay_2026_holdout.csv` | Holdout dataset for evaluating model performance |

## Model Evaluation

NextLap evaluates its next-lap forecasts against a circuit-median baseline to assess whether the machine learning model provides useful predictive improvements.

Historical replay supports comparisons between predicted and actual lap times across completed races. The holdout dataset provides additional data for evaluating generalization.

Model performance should be interpreted in the context of race conditions, tyre state, safety-car periods, and other factors that affect lap times.

## Technology Stack

- **Language:** Python
- **Machine Learning:** Scikit-learn
- **Data Source:** OpenF1 API
- **Frontend:** Web technologies
- **Deployment:** Local Python server and Cloudflare Pages for the hosted demo

## License

This project is released under the [MIT License](LICENSE).

## Disclaimer

NextLap is an independent, non-commercial fan project. It is not affiliated with, associated with, or endorsed by Formula 1, Formula One Management (FOM), the FIA, or any Formula 1 team.

All Formula 1 trademarks, driver names, team names, and related marks belong to their respective owners.
