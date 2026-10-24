<p align="center">
  <img src="web/assets/icon.png" alt="NextLap logo" width="360">
</p>

# NextLap

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/)

A local Formula 1 dashboard for tracking live race sessions and evaluating historical next-lap forecasts in real time.

---

## 🚀 Key Features

* **Live Monitor:** Connects to OpenF1 during live sessions and generates real-time telemetry forecasts as new lap data arrives.
* **Historical Replay:** Enables step-by-step review of completed past races, comparing model forecasts directly against actual completed laps.
* **Prediction Benchmarking:** Evaluates performance by comparing a Gradient Boosting model against a circuit-median baseline.
* **Rich Race Context:** Displays comprehensive telemetry and session context, including selected season, race, driver, team, and circuit information.

> **Note:** *Historical Replay is designed for evaluating past model accuracy on completed races and does not generate live predictions.*

---

## 📸 Screenshots

### Live Monitor
*Displays real-time forecasts updated continuously as race data streams in.*

![NextLap live monitor](docs/screenshots/live-monitor.png)

### Historical Replay
*Inspect completed races turn-by-turn and forecast-by-forecast.*

![NextLap historical replay](docs/screenshots/historical-replay.png)

---

## 🛠️ How to Run Locally

### Prerequisites
Ensure you have Python 3.9+ and project dependencies installed.

### Start the Dashboard
Run the local server script from the repository root:

```powershell
python local_app.py
