import requests, pandas as pd
msgs = requests.get("https://api.openf1.org/v1/race_control",
                       params={"session_key": SESSION_KEY}).json()
rc = pd.DataFrame(msgs)
print(rc[["lap_number", "category", "flag", "message"]].to_string())