import os
import fastf1

# Saves downloaded data so you only download each race once
os.makedirs("f1_cache", exist_ok=True)
fastf1.Cache.enable_cache("f1_cache")

# Load the 2023 Italian Grand Prix race
session = fastf1.get_session(2023, "Monza", "R")
session.load(telemetry=False, weather=True, messages=False)

laps = session.laps

# Pick the columns we care about
table = laps[["Driver", "Team", "LapNumber", "LapTime", "Compound", "TyreLife"]]
print(table.head(20))
print("Total laps in this race:", len(table))

# Turn lap time into plain seconds (we'll need this later)
table = table.copy()
table["LapSeconds"] = table["LapTime"].dt.total_seconds()
print(table[["Driver", "LapNumber", "LapSeconds"]].head(10))

import matplotlib.pyplot as plt

ver = table[table["Driver"] == "VER"]
plt.plot(ver["LapNumber"], ver["LapSeconds"])
plt.xlabel("Lap number")
plt.ylabel("Lap time (s)")
plt.title("VER lap times, Monza 2023")
plt.show()

laps = session.laps
clean = laps.pick_wo_box().pick_quicklaps()   # removes pit laps and very slow laps
clean = clean[clean["LapNumber"] > 1]         # removes lap 1
print("Before cleaning:", len(laps), " After:", len(clean))

ver_clean = clean[clean["Driver"] == "VER"].copy()
ver_clean["LapSeconds"] = ver_clean["LapTime"].dt.total_seconds()

plt.plot(ver_clean["LapNumber"], ver_clean["LapSeconds"])
plt.xlabel("Lap number")
plt.ylabel("Lap time (s)")
plt.title("VER lap times, cleaned")
plt.show()

clean = clean.copy()
clean["LapSeconds"] = clean["LapTime"].dt.total_seconds()

drivers = ["VER", "PER", "LEC", "NOR"]

for d in drivers:
    one = clean[clean["Driver"] == d]
    plt.plot(one["LapNumber"], one["LapSeconds"], label=d)

plt.xlabel("Lap number")
plt.ylabel("Lap time (s)")
plt.title("Cleaned lap times, Monza 2023")
plt.legend()
plt.show()

ver_all = laps[laps["Driver"] == "VER"]
print(ver_all[["LapNumber", "Stint", "Compound", "TyreLife"]].iloc[17:25])

no_pits = laps.pick_wo_box().copy()
no_pits["LapSeconds"] = no_pits["LapTime"].dt.total_seconds()
by_lap = no_pits.groupby("LapNumber")["LapSeconds"].median()

plt.plot(by_lap.index, by_lap.values)
plt.xlabel("Lap number")
plt.ylabel("Median lap time, all drivers (s)")
plt.title("Race pace across the whole field")
plt.show()

step1 = laps.pick_wo_box()
step2 = step1.pick_quicklaps()
print("All laps:", len(laps))
print("After removing pit laps:", len(step1))
print("After removing slow laps:", len(step2))

step1 = laps.pick_wo_box()
step2 = step1.pick_quicklaps()

removed = step1[~step1.index.isin(step2.index)]
print(removed["LapNumber"].value_counts().sort_index())
print(removed[["Driver", "LapNumber", "LapTime", "Position"]].sort_values("LapNumber").tail(12))
clean = clean.dropna(subset=["LapTime"])

import pandas as pd

def get_clean_laps(year, race, session_type="R"):
    session = fastf1.get_session(year, race, session_type)
    session.load(telemetry=False, weather=True, messages=False)
    laps = session.laps

    step1 = laps.pick_wo_box()                         # remove pit laps
    step2 = step1.pick_quicklaps()                     # remove very slow laps
    step3 = step2[step2["LapNumber"] > 1]              # remove lap 1
    step4 = step3.dropna(subset=["LapTime"])           # remove rows with no time

    print(year, race, "| all:", len(laps), "| no pit:", len(step1),
          "| no slow:", len(step2), "| no lap 1:", len(step3),
          "| final:", len(step4))

    clean = step4.copy()
    clean["LapSeconds"] = clean["LapTime"].dt.total_seconds()
    clean["Year"] = year
    clean["Circuit"] = race
    return clean