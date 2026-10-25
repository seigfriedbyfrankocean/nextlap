import fastf1

fastf1.set_log_level("CRITICAL")               # hide the warning spam
fastf1.Cache.enable_cache("f1_cache")

YEARS = [2023, 2024, 2025, 2026]
ROUNDS = [1, 4, 8, 12, 16]                     # a spread through each season

print(f"{'Year':<6}{'Round':<7}{'Event':<32}Result")
for year in YEARS:
    for rnd in ROUNDS:
        try:
            session = fastf1.get_session(year, rnd, "R")
            name = session.event["EventName"]
        except Exception as e:
            print(f"{year:<6}{rnd:<7}{'?':<32}no such round ({type(e).__name__})")
            continue
        try:
            session.load(laps=True, telemetry=False, weather=False, messages=False)
            n = len(session.laps)
            print(f"{year:<6}{rnd:<7}{name:<32}OK ({n} laps)")
        except Exception as e:
            print(f"{year:<6}{rnd:<7}{name:<32}NOT AVAILABLE")