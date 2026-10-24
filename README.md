<p align="center">
  <img src="web/assets/icon.png" alt="NextLap, always a lap ahead" width="360">
</p>

# NextLap

NextLap is a local Formula 1 dashboard for next lap forecasts. It brings live session monitoring and historical race replay together in one place.

## Run the dashboard

From the project folder, start the local server with:

```powershell
python local_app.py
```

Then open [http://127.0.0.1:8765](http://127.0.0.1:8765) in your browser. Stop the server with `Ctrl+C`.

## What it includes

The live monitor checks an OpenF1 session and records forecasts as new lap data arrives. Historical replay lets you review past races and compare next lap predictions with the laps that followed.

The dashboard uses a trained gradient boosting model for its model based forecasts and includes a circuit median baseline for comparison. Historical replay is retrospective and does not represent a live prediction.
