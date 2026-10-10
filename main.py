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