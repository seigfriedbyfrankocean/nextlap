import fastf1
fastf1.set_log_level("DEBUG")
fastf1.Cache.enable_cache("f1_cache")
s = fastf1.get_session(2023, 2, "R")
s.load(telemetry=False, weather=False, messages=False)