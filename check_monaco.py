
import requests
import pandas as pd

BASE = "https://api.openf1.org/v1"
SESSION = 11299

def fetch(endpoint):
    r = requests.get(
        f"{BASE}/{endpoint}",
        params={"session_key": SESSION},
        timeout=60,
    )
    r.raise_for_status()
    return pd.DataFrame(r.json())

laps = fetch("laps")
print("Raw lap records:", len(laps))

if not laps.empty:
    cols = [
        c for c in [
            "driver_number", "lap_number", "lap_duration",
            "is_pit_out_lap", "date_start"
        ]
        if c in laps.columns
    ]

    print("\nRaw lap records, laps 69-74:")
    print(
        laps[laps["lap_number"].between(69, 74)]
        .sort_values(["lap_number", "driver_number"])[cols]
        .to_string(index=False)
    )

control = fetch("race_control")
print("\nRace-control records:", len(control))

if not control.empty:
    cols = [
        c for c in ["date", "category", "flag", "message"]
        if c in control.columns
    ]

    relevant = control[
        control["message"].astype(str).str.contains(
            "SAFETY CAR|VSC|RED FLAG|GREEN FLAG|GREEN LIGHT|"
            "IN THIS LAP|CHEQUERED|YELLOW",
            case=False,
            regex=True,
            na=False,
        )
    ]

    print("\nRelevant race-control messages:")
    print(relevant[cols].tail(60).to_string(index=False))

if not control.empty:
    control["date"] = pd.to_datetime(control["date"], utc=True)

    start = pd.Timestamp("2026-06-07T14:30:00Z")
    end = pd.Timestamp("2026-06-07T15:20:00Z")

    print("\nALL race-control messages from 14:30 to 15:20 UTC:")
    window = control[
        control["date"].between(start, end)
    ].sort_values("date")

    print(
        window[["date", "category", "flag", "message"]]
        .to_string(index=False)
    )