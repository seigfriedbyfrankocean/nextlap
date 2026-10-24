<p align="center">
  <img src="web/assets/icon.png" alt="NextLap logo" width="360">
</p>

# NextLap

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/)

A local Formula 1 dashboard for tracking live race sessions and evaluating historical next-lap forecasts in real time.

---

## Key Features

* **Live Monitor:** Connects to OpenF1 during live sessions and generates real-time telemetry forecasts as new lap data arrives.
* **Historical Replay:** Enables step-by-step review of completed past races, comparing model forecasts directly against actual completed laps.
* **Prediction Benchmarking:** Evaluates performance by comparing a Gradient Boosting model against a circuit-median baseline.
* **Rich Race Context:** Displays comprehensive telemetry and session context, including selected season, race, driver, team, and circuit information.

> **Note:** *Historical Replay is designed for evaluating past model accuracy on completed races and does not generate live predictions.*

---

## Screenshots

### Live Monitor
*Displays real-time forecasts updated continuously as race data streams in.*

![NextLap live monitor](docs/screenshots/live-monitor.png)

### Historical Replay
*Inspect completed races turn-by-turn and forecast-by-forecast.*

![NextLap historical replay](docs/screenshots/historical-replay.png)

---

## How to Run Locally

### Prerequisites
Ensure you have Python 3.9+ and project dependencies installed.

### Start the Dashboard
Run the local server script from the repository root:

```powershell
python local_app.py
Open http://127.0.0.1:8765 in your browser.To stop the server, press Ctrl + C in your terminal.Hosted DemoTry the interactive web demo at nextlap.pages.dev.Replay Coverage: Includes pre-rendered replay data from the 2023 through 2026 F1 seasons.Live Features: Live session monitoring requires a local server connection to OpenF1 and is only supported when running the Python application locally.Rebuilding Static Demo DataTo update or rebuild the static replay dataset after changing model parameters or data:PowerShellpython build_static_demo.py
Project ArchitectureFile / DirectoryDescriptionlocal_app.pyLocal web server and dashboard entry pointweb/Web front-end UI, assets, fonts, and circuit SVG layoutspredict_live.pyReal-time telemetry ingestion and streaming forecast enginemodel_fit.pyTraining script for the Gradient Boosting modelbuild_static_demo.pyPre-computes static prediction data for the hosted demolaps_sample_v3.csvCore historical lap dataset used for training and testingreplay_2026_holdout.csvHoldout evaluation dataset for validationLicenseThis project is open-source and released under the MIT License.DisclaimerThis project is an independent, non-commercial fan creation and is not affiliated with, associated with, or endorsed by Formula 1, FOM, FIA, or any affiliated teams. All Formula 1 trademarks, team names, driver names, and related marks belong to their respective owners.
<ElicitationsGroup message="Need any further adjustments to this README?">
  <Elicitation label="Add Installation Section" query="Can you add a step-by-step installation section including pip install steps and virtual environment setup?"/>
  <Elicitation label="Add Badge Options" query="Can you add build status, dependencies, or GitHub star badges to the header?"/>
  <Elicitation label="Format for GitHub Actions" query="Can you add a section on setting up GitHub Actions to deploy the Cloudflare Pages demo automatically?"/>
</ElicitationsGroup>
