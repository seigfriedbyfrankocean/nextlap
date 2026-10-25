import time
import requests
import pandas as pd

BASE = "https://api.openf1.org/v1"
PAUSE = 1.0                                    # be gentle with the free API


def get(endpoint, **params):
    r = requests.get(f"{BASE}/{endpoint}", params=params, timeout=60)
    print(f"GET {endpoint} {params} -> HTTP {r.status_code}")
    r.raise_for_status()
    time.sleep(PAUSE)
    return pd.DataFrame(r.json())


# 1. How many race sessions does OpenF1 have per season?
print("=== Race sessions per season ===")
sessions = {}
for year in (2023, 2024, 2025, 2026):
    try:
        df = get("sessions", year=year, session_name="Race")
    except Exception as e:
        print(f"{year}: FAILED ({e})")
        continue
    sessions[year] = df
    print(f"{year}: {len(df)} races")

non_empty = [y for y, d in sessions.items() if len(d) > 0]
if not non_empty:
    raise SystemExit("No race sessions came back, so there is nothing to inspect.")

# 2. Look at the fields each endpoint returns for one sample race
year = non_empty[0]
sample = sessions[year].iloc[0]
key = int(sample["session_key"])
print(f"\n=== Sample race: {year}, session_key {key} ===")
print(sample.to_dict())

for endpoint in ["laps", "stints", "weather", "drivers", "race_control", "pit"]:
    try:
        df = get(endpoint, session_key=key)
    except Exception as e:
        print(f"\n--- {endpoint}: FAILED ({e}) ---")
        continue
    print(f"\n--- {endpoint}: {len(df)} rows ---")
    print("Columns:", list(df.columns))
    print(df.head(3).to_string())