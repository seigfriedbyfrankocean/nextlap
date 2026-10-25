import os
import fastf1
import pandas as pd

os.makedirs("f1_cache", exist_ok=True)
fastf1.Cache.enable_cache("f1_cache")


def get_clean_laps(year, race, session_type="R"):
    session = fastf1.get_session(year, race, session_type)
    session.load(telemetry=False, weather=True, messages=False)
    laps = session.laps
    weather = laps.get_weather_data()
    laps["TrackTemp"] = weather["TrackTemp"].values
    laps["AirTemp"] = weather["AirTemp"].values
    

    step1 = laps.pick_wo_box()                         # remove pit laps
    bad_status = step1["TrackStatus"].astype(str).str.contains("[4567]")
    step2 = step1[~bad_status]                       # drop safety car, red flag, VSC laps
    step2 = step2.pick_quicklaps(threshold=1.15)     # looser slow lap rule                    # remove very slow laps
    removed = step1[~step1.index.isin(step2.index)]
    print(removed["LapNumber"].value_counts().sort_index().to_string())
    step3 = step2[step2["LapNumber"] > 1]              # remove lap 1
    step4 = step3.dropna(subset=["LapTime"])           # remove rows with no time

    print(year, race, "| all:", len(laps), "| no pit:", len(step1),
          "| no slow:", len(step2), "| no lap 1:", len(step3),
          "| final:", len(step4))
    print(race, "- laps removed by the slow filter (lap number, count):")
    print(race, "- track status of removed laps:")
    print(removed["TrackStatus"].value_counts().to_string())

    clean = step4.copy()
    clean["LapSeconds"] = clean["LapTime"].dt.total_seconds()
    clean["Year"] = year
    clean["Circuit"] = race
    return clean


all_clean = []
for race in ["Monza", "Bahrain", "Silverstone"]:
    all_clean.append(get_clean_laps(2023, race))

data = pd.concat(all_clean)
print("Total clean laps:", len(data))
data.to_csv("laps_sample.csv", index=False)
