<p align="center">
  <img src="web/assets/icon.png" alt="NextLap, always a lap ahead" width="360">
</p>

# NextLap

A local Formula 1 dashboard for following live race sessions and exploring historical next lap forecasts.

## What it does

* **Live monitor:** Follows an OpenF1 race session and records a forecast when new lap data is available.
* **Historical replay:** Steps through past races and compares each forecast with the lap that followed.
* **Prediction methods:** Compares the gradient boosting model with a circuit median baseline.
* **Race context:** Shows the selected season, race, driver, team, and circuit information in the dashboard.

Historical replay is a review of completed races. It is not a live prediction.

## Screenshots

The live monitor shows forecasts as race session data arrives.

![NextLap live monitor](docs/screenshots/live-monitor.png)

Historical replay lets you inspect a completed race one forecast at a time.

![NextLap historical replay](docs/screenshots/historical-replay.png)`n`n## How to run it

Use a Python environment with the project dependencies installed. From the project folder, start the dashboard:

```powershell
python local_app.py
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765) in your browser. Stop the server with `Ctrl+C`.

## Hosted demo

Visit [nextlap.pages.dev](https://nextlap.pages.dev) to try the hosted portfolio demo. It opens in historical replay and includes replay data from the 2023 through 2026 seasons. Live monitoring is available when you run the Python app locally because it needs the server to connect to OpenF1.

The hosted historical replay uses bundled prediction data generated from the project dataset and model. To rebuild it after changing the data, run `python build_static_demo.py` in an environment with the project dependencies installed.

## Project files

* `local_app.py` serves the local dashboard.
* `web/` contains the dashboard page, branding, fonts, and circuit layouts.
* `predict_live.py` handles live session forecasts.
* `model_fit.py` contains the gradient boosting model training code.
* `build_static_demo.py` generates the replay data used by the hosted portfolio demo.
* `laps_sample_v3.csv` contains the historical lap data used by the project.
* `replay_2026_holdout.csv` contains the held out replay data.

## License

The project code is available under the MIT License. See `LICENSE` for details.

The Formula 1 name, team names, driver names, and related marks belong to their respective owners. This project is an independent fan project and is not affiliated with or endorsed by Formula 1 or the teams.
