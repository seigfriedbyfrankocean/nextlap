"""Local dashboard for the F1 next-lap predictor (standard library only)."""
import argparse
import json
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from predict_live import DEFAULT_LOG_DB, get_frame, predict_live, resolve_session

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
REPLAY_DATA = ROOT / "replay_2026_holdout.csv"
REPLAY_SOURCE_DATA = ROOT / "laps_sample_v3.csv"
RACE_COUNTRY_CODES = {
    "sakhir": "BHR", "jeddah": "SAU", "melbourne": "AUS", "shanghai": "CHN",
    "suzuka": "JPN", "miami": "USA", "montreal": "CAN", "monte carlo": "MON",
    "catalunya": "ESP", "spielberg": "AUT", "silverstone": "GBR",
    "spa-francorchamps": "BEL", "hungaroring": "HUN", "monza": "ITA",
    "baku": "AZE", "singapore": "SGP", "lusail": "QAT", "austin": "USA",
    "mexico city": "MEX", "interlagos": "BRA", "las vegas": "USA",
    "yas marina circuit": "UAE", "imola": "ITA", "zandvoort": "NED",
    "madring": "ESP",
}
F1_TEAM_LOGOS = {
    "mercedes": ("2025", "mercedes", "2025mercedeslogowhite.webp"),
    "ferrari": ("2025", "ferrari", "2025ferrarilogolight.webp"),
    "mclaren": ("2025", "mclaren", "2025mclarenlogowhite.webp"),
    "red bull racing": ("2025", "redbullracing", "2025redbullracinglogowhite.webp"),
    "racing bulls": ("2025", "racingbulls", "2025racingbullslogowhite.webp"),
    "alpine": ("2025", "alpine", "2025alpinelogowhite.webp"),
    "alpine racing": ("2025", "alpine", "2025alpinelogowhite.webp"),
    "haas f1 team": ("2025", "haas", "2025haaslogowhite.webp"),
    "audi": ("2026", "audi", "2026audilogowhite.webp"),
    "williams": ("2025", "williams", "2025williamslogowhite.webp"),
    "aston martin": ("2025", "astonmartin", "2025astonmartinlogowhite.webp"),
    "cadillac": ("2026", "cadillac", "2026cadillaclogowhite.webp"),
}
REPLAY_HEADSHOT_PATHS = {
    "RUS": "G/GEORUS01_George_Russell/georus01.png",
    "ANT": "K/ANDANT01_Kimi_Antonelli/andant01.png",
    "LEC": "C/CHALEC01_Charles_Leclerc/chalec01.png",
    "HAM": "L/LEWHAM01_Lewis_Hamilton/lewham01.png",
    "NOR": "L/LANNOR01_Lando_Norris/lannor01.png",
    "PIA": "O/OSCPIA01_Oscar_Piastri/oscpia01.png",
    "VER": "M/MAXVER01_Max_Verstappen/maxver01.png",
    "HAD": "I/ISAHAD01_Isack_Hadjar/isahad01.png",
    "LAW": "L/LIALAW01_Liam_Lawson/lialaw01.png",
    "LIN": "A/ARVLIN01_Arvid_Lindblad/arvlin01.png",
    "GAS": "P/PIEGAS01_Pierre_Gasly/piegas01.png",
    "COL": "F/FRACOL01_Franco_Colapinto/fracol01.png",
    "OCO": "E/ESTOCO01_Esteban_Ocon/estoco01.png",
    "BEA": "O/OLIBEA01_Oliver_Bearman/olibea01.png",
    "HUL": "N/NICHUL01_Nico_Hulkenberg/nichul01.png",
    "BOR": "G/GABBOR01_Gabriel_Bortoleto/gabbor01.png",
    "SAI": "C/CARSAI01_Carlos_Sainz/carsai01.png",
    "ALB": "A/ALEALB01_Alexander_Albon/alealb01.png",
    "ALO": "F/FERALO01_Fernando_Alonso/feralo01.png",
    "STR": "L/LANSTR01_Lance_Stroll/lanstr01.png",
    "PER": "S/SERPER01_Sergio_Perez/serper01.png",
    "BOT": "V/VALBOT01_Valtteri_Bottas/valbot01.png",
}
REPLAY_DRIVER_META = {
    "RUS": ("George Russell", 63, "GBR", "Mercedes", "00A19B"),
    "ANT": ("Kimi Antonelli", 12, "ITA", "Mercedes", "00A19B"),
    "LEC": ("Charles Leclerc", 16, "MON", "Ferrari", "E8002D"),
    "HAM": ("Lewis Hamilton", 44, "GBR", "Ferrari", "E8002D"),
    "NOR": ("Lando Norris", 4, "GBR", "McLaren", "FF8000"),
    "PIA": ("Oscar Piastri", 81, "AUS", "McLaren", "FF8000"),
    "VER": ("Max Verstappen", 1, "NED", "Red Bull Racing", "3671C6"),
    "HAD": ("Isack Hadjar", 6, "FRA", "Red Bull Racing", "3671C6"),
    "LAW": ("Liam Lawson", 30, "NZL", "Racing Bulls", "6692FF"),
    "LIN": ("Arvid Lindblad", 41, "GBR", "Racing Bulls", "6692FF"),
    "GAS": ("Pierre Gasly", 10, "FRA", "Alpine", "0093CC"),
    "COL": ("Franco Colapinto", 43, "ARG", "Alpine", "0093CC"),
    "OCO": ("Esteban Ocon", 31, "FRA", "Haas F1 Team", "B6BABD"),
    "BEA": ("Oliver Bearman", 87, "GBR", "Haas F1 Team", "B6BABD"),
    "HUL": ("Nico Hulkenberg", 27, "GER", "Audi", "F50537"),
    "BOR": ("Gabriel Bortoleto", 5, "BRA", "Audi", "F50537"),
    "SAI": ("Carlos Sainz", 55, "ESP", "Williams", "1868DB"),
    "ALB": ("Alexander Albon", 23, "THA", "Williams", "1868DB"),
    "ALO": ("Fernando Alonso", 14, "ESP", "Aston Martin", "229971"),
    "STR": ("Lance Stroll", 18, "CAN", "Aston Martin", "229971"),
    "PER": ("Sergio Perez", 11, "MEX", "Cadillac", "1E1E1E"),
    "BOT": ("Valtteri Bottas", 77, "FIN", "Cadillac", "1E1E1E"),
}
HISTORICAL_DRIVER_META = {
    "DEV": ("Nyck de Vries", 21, "NED"),
    "RIC": ("Daniel Ricciardo", 3, "AUS"),
    "MAG": ("Kevin Magnussen", 20, "DEN"),
    "SAR": ("Logan Sargeant", 2, "USA"),
    "ZHO": ("Zhou Guanyu", 24, "CHN"),
    "TSU": ("Yuki Tsunoda", 22, "JPN"),
    "DOO": ("Jack Doohan", 7, "AUS"),
}
HISTORICAL_NUMBER_OVERRIDES = {2023: {"LAW": 40}}
CIRCUIT_SVG_IDS = {
    "austin": "austin-1", "sakhir": "bahrain-3", "baku": "baku-1",
    "catalunya": "catalunya-6", "hungaroring": "hungaroring-3",
    "imola": "imola-3", "interlagos": "interlagos-2", "jeddah": "jeddah-1",
    "las vegas": "las-vegas-1", "lusail": "lusail-1", "madring": "madring-1",
    "singapore": "marina-bay-4", "melbourne": "melbourne-2",
    "mexico city": "mexico-city-3", "miami": "miami-1", "monte carlo": "monaco-6",
    "montreal": "montreal-6", "monza": "monza-7", "shanghai": "shanghai-1",
    "silverstone": "silverstone-8", "spa-francorchamps": "spa-francorchamps-4",
    "spielberg": "spielberg-3", "suzuka": "suzuka-2", "yas marina circuit": "yas-marina-2",
    "zandvoort": "zandvoort-5",
}
DRIVER_ASSET_SLUGS = {
    "DEV": "nycdev01", "RIC": "danric01", "MAG": "kevmag01",
    "SAR": "logsar01", "ZHO": "zhouzh01", "TSU": "yuktsu01",
    "DOO": "jacdoo01",
}
TEAM_COLOURS = {
    "mercedes": "00A19B", "ferrari": "E8002D", "mclaren": "FF8000",
    "red bull racing": "3671C6", "alphatauri": "536B8A",
    "racing bulls": "6692FF", "rb": "6692FF", "alpine": "0093CC",
    "haas f1 team": "B6BABD", "williams": "1868DB",
    "aston martin": "229971", "alfa romeo": "C92D4B",
    "kick sauber": "52E252", "audi": "F50537", "cadillac": "1E1E1E",
}

F1_TEAM_CARS = {
    "mercedes": "mercedes",
    "ferrari": "ferrari",
    "mclaren": "mclaren",
    "red bull racing": "redbullracing",
    "racing bulls": "racingbulls",
    "alpine": "alpine",
    "haas f1 team": "haas",
    "audi": "audi",
    "williams": "williams",
    "aston martin": "astonmartin",
    "cadillac": "cadillac",
}

F1_PROFILE_IMAGES = {
    "RUS": "mercedes/georus01/2026mercedesgeorus01right.webp",
    "ANT": "mercedes/andant01/2026mercedesandant01right.webp",
    "LEC": "ferrari/chalec01/2026ferrarichalec01right.webp",
    "HAM": "ferrari/lewham01/2026ferrarilewham01right.webp",
    "NOR": "mclaren/lannor01/2026mclarenlannor01right.webp",
    "PIA": "mclaren/oscpia01/2026mclarenoscpia01right.webp",
    "VER": "redbullracing/maxver01/2026redbullracingmaxver01right.webp",
    "HAD": "redbullracing/isahad01/2026redbullracingisahad01right.webp",
    "LAW": "racingbulls/lialaw01/2026racingbullslialaw01right.webp",
    "LIN": "racingbulls/arvlin01/2026racingbullsarvlin01right.webp",
    "GAS": "alpine/piegas01/2026alpinepiegas01right.webp",
    "COL": "alpine/fracol01/2026alpinefracol01right.webp",
    "OCO": "haas/estoco01/2026haasestoco01right.webp",
    "BEA": "haas/olibea01/2026haasolibea01right.webp",
    "HUL": "audi/nichul01/2026audinichul01right.webp",
    "BOR": "audi/gabbor01/2026audigabbor01right.webp",
    "SAI": "williams/carsai01/2026williamscarsai01right.webp",
    "ALB": "williams/alealb01/2026williamsalealb01right.webp",
    "ALO": "astonmartin/feralo01/2026astonmartinferalo01right.webp",
    "STR": "astonmartin/lanstr01/2026astonmartinlanstr01right.webp",
    "PER": "cadillac/serper01/2026cadillacserper01right.webp",
    "BOT": "cadillac/valbot01/2026cadillacvalbot01right.webp",
}

def _team_asset_slug(team_name, year=2026):
    team = str(team_name or "").strip().casefold()
    if "red bull" in team:
        return "redbullracing"
    if "alpha tauri" in team or "alphatauri" in team:
        return "alphatauri" if int(year) <= 2023 else "racingbulls"
    if "racing bulls" in team or team == "rb":
        return "racingbulls"
    if "mercedes" in team:
        return "mercedes"
    if "ferrari" in team:
        return "ferrari"
    if "mclaren" in team:
        return "mclaren"
    if "alpine" in team:
        return "alpine"
    if "haas" in team:
        return "haas"
    if "williams" in team:
        return "williams"
    if "aston martin" in team or "racing point" in team:
        return "astonmartin"
    if "alfa romeo" in team:
        return "alfaromeo"
    if "kick sauber" in team or team == "sauber":
        return "kicksauber" if int(year) >= 2024 else "alfaromeo"
    if "audi" in team:
        return "audi"
    if "cadillac" in team:
        return "cadillac"
    return ""


def team_logo_url(team_name, year=2026):
    year = int(year or 2026)
    team = str(team_name or "").strip().casefold()
    if "alfa romeo" in team:
        return "https://upload.wikimedia.org/wikipedia/commons/d/d4/Alfa_Romeo_F1_Team_Stake_Logo.svg"
    slug = _team_asset_slug(team, year)
    if not slug:
        return ""
    key = (
        "red bull racing" if "red bull" in team else
        "racing bulls" if slug in ("racingbulls", "alphatauri") else
        "haas f1 team" if slug == "haas" else
        "alpine" if slug == "alpine" else team
    )
    item = F1_TEAM_LOGOS.get(key)
    if item:
        logo_year, logo_slug, filename = item
        return f"https://media.formula1.com/image/upload/c_fit%2Ch_128/q_95/v1740000001/common/f1/{logo_year}/{logo_slug}/{filename}"
    if slug == "alfaromeo":
        slug = "alfa-romeo"
    filename = f"{year}{slug}{'logolight' if slug in ('ferrari', 'alfa-romeo') else 'logowhite'}.webp"
    return f"https://media.formula1.com/image/upload/c_fit%2Ch_128/q_95/v1740000001/common/f1/{year}/{slug}/{filename}"


def team_car_url(team_name, year=2026):
    year = int(year or 2026)
    slug = _team_asset_slug(team_name, year)
    if not slug:
        return ""
    if year < 2025:
        legacy_slug = {
            "redbullracing": "red-bull-racing", "alphatauri": "alphatauri",
            "alfaromeo": "alfa-romeo", "astonmartin": "aston-martin",
            "kicksauber": "kick-sauber",
        }.get(slug, slug)
        return f"https://media.formula1.com/d_team_car_fallback_image.png/content/dam/fom-website/teams/{year}/{legacy_slug}.png.transform/9col-retina/image.png"
    return f"https://media.formula1.com/image/upload/c_lfill%2Cw_3392/q_auto/v1740000001/common/f1/{year}/{slug}/{year}{slug}carright.webp"


def season_driver_hero_url(acronym, team_name, year):
    acronym = str(acronym or "").upper()
    year = int(year or 0)
    if year < 2023 or year > 2026:
        return ""
    headshot_path = REPLAY_HEADSHOT_PATHS.get(acronym, "")
    if headshot_path:
        reference = headshot_path.split("/")[1].split("_")[0]
    else:
        reference = DRIVER_ASSET_SLUGS.get(acronym, "").upper()
    if not reference:
        return ""
    return f"https://media.formula1.com/content/dam/fom-website/2018-redesign-assets/drivers/{year}/{reference}.png"


def replay_driver_data(acronym, year=2026, team_name=None):
    acronym = str(acronym).upper()
    year = int(year or 2026)
    meta = REPLAY_DRIVER_META.get(acronym)
    historical = HISTORICAL_DRIVER_META.get(acronym)
    if meta:
        name, number, country, default_team, _ = meta
    elif historical:
        name, number, country = historical
        default_team = ""
    else:
        name, number, country, default_team = acronym, None, "", ""
    team = str(team_name or default_team)
    number = HISTORICAL_NUMBER_OVERRIDES.get(year, {}).get(acronym, number)
    colour = TEAM_COLOURS.get(team.strip().casefold(), (meta[4] if meta else "465365"))
    hero = season_driver_hero_url(acronym, team, year)
    headshot_path = REPLAY_HEADSHOT_PATHS.get(acronym, "")
    headshot = f"https://media.formula1.com/content/dam/fom-website/drivers/{headshot_path}" if headshot_path else ""
    return {
        "acronym": acronym, "name": name, "driver_number": number,
        "country_code": country, "team_name": team, "team_colour": colour,
        "team_logo_url": team_logo_url(team, year),
        "car_image_url": team_car_url(team, year),
        "hero_url": hero, "headshot_url": headshot, "season_year": year,
    }


def circuit_svg_url(circuit):
    layout = CIRCUIT_SVG_IDS.get(str(circuit or "").strip().casefold())
    return f"/assets/circuits/{layout}.svg" if layout else ""


MODEL_CAT = ["Driver", "Car", "Circuit", "Compound"]
MODEL_NUM = ["TyreLife", "TyreLife_sq", "Tyre_SOFT", "Tyre_MEDIUM", "Tyre_HARD", "TrackTemp", "AirTemp", "FreshTyre", "LapSeconds"]
MODEL_REQUIRED = ["Year", "Round", "Driver", "Team", "Circuit", "Compound", "TyreLife", "LapNumber", "TrackTemp", "AirTemp", "FreshTyre", "LapSeconds", "NextLapSeconds"]


def _model_features(pd, rows):
    features = rows.copy()
    features["Car"] = features["Team"].astype(str) + " " + features["Year"].astype(int).astype(str)
    features["TyreLife_sq"] = pd.to_numeric(features["TyreLife"], errors="coerce") ** 2
    for compound in ("SOFT", "MEDIUM", "HARD"):
        features[f"Tyre_{compound}"] = pd.to_numeric(features["TyreLife"], errors="coerce").where(features["Compound"].astype(str).str.upper() == compound, 0.0)
    features["FreshTyre"] = features["FreshTyre"].astype(int)
    return features


def _fit_replay_model(pd, train):
    from sklearn.compose import ColumnTransformer
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import OrdinalEncoder

    prepared = _model_features(pd, train.dropna(subset=MODEL_REQUIRED))
    if prepared.empty:
        return None, 0
    transform = ColumnTransformer([
        ("cat", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1), MODEL_CAT),
        ("num", "passthrough", MODEL_NUM),
    ])
    estimator = HistGradientBoostingRegressor(
        max_iter=160, learning_rate=0.05, random_state=0,
        categorical_features=[True] * len(MODEL_CAT) + [False] * len(MODEL_NUM),
    )
    model = make_pipeline(transform, estimator)
    model.fit(prepared[MODEL_CAT + MODEL_NUM], prepared["NextLapSeconds"] - prepared["LapSeconds"])
    return model, len(prepared)


def _build_replay_cache(pd):
    if not REPLAY_SOURCE_DATA.is_file():
        if not REPLAY_DATA.is_file():
            raise FileNotFoundError(f"Replay source is missing: {REPLAY_SOURCE_DATA.name}")
        return pd.read_csv(REPLAY_DATA)

    source = pd.read_csv(REPLAY_SOURCE_DATA)
    source = source.dropna(subset=["Year", "Round", "Circuit", "Driver", "LapNumber", "LapSeconds", "NextLapSeconds"]).copy()
    source["Year"] = pd.to_numeric(source["Year"], errors="coerce")
    source["Round"] = pd.to_numeric(source["Round"], errors="coerce")
    source["LapNumber"] = pd.to_numeric(source["LapNumber"], errors="coerce")
    source["Circuit"] = source["Circuit"].astype(str).str.strip()
    source["Driver"] = source["Driver"].astype(str).str.upper()
    model_by_year = {}
    historical = []
    for year in sorted(int(value) for value in source["Year"].dropna().unique() if int(value) < 2026):
        season = source[source["Year"] == year].copy()
        training = source[source["Year"] < year]
        if training.empty:
            circuit_deltas = pd.Series(dtype=float)
            circuit_counts = pd.Series(dtype=float)
            global_delta = 0.0
        else:
            training = training.assign(_Delta=training["NextLapSeconds"] - training["LapSeconds"])
            grouped = training.groupby("Circuit")["_Delta"].agg(["median", "count"])
            circuit_deltas = grouped["median"]
            circuit_counts = grouped["count"]
            global_delta = float(training["NextLapSeconds"].sub(training["LapSeconds"]).median())
        mapped = season["Circuit"].map(circuit_deltas)
        unseen = mapped.isna()
        season["CircuitDeltaSeconds"] = mapped.fillna(global_delta)
        season["CircuitTrainingRows"] = season["Circuit"].map(circuit_counts).fillna(len(training)).astype(int)
        season["PersistencePrediction"] = season["LapSeconds"]
        season["PersistenceAbsError"] = (season["NextLapSeconds"] - season["LapSeconds"]).abs()
        season["CircuitPrediction"] = season["LapSeconds"] + season["CircuitDeltaSeconds"]
        season["CircuitAbsError"] = (season["NextLapSeconds"] - season["CircuitPrediction"]).abs()
        season["CurrentLapSeconds"] = season["LapSeconds"]
        season["ActualNextLapSeconds"] = season["NextLapSeconds"]
        model, training_rows = _fit_replay_model(pd, source[source["Year"] < year])
        if model is None:
            season["MLPrediction"] = float("nan")
            season["MLAbsError"] = float("nan")
        else:
            prepared = _model_features(pd, season)
            season["MLPrediction"] = season["LapSeconds"] + model.predict(prepared[MODEL_CAT + MODEL_NUM])
            season["MLAbsError"] = (season["NextLapSeconds"] - season["MLPrediction"]).abs()
        season["MLTrainingRows"] = training_rows
        model_by_year[year] = (model, training_rows)
        historical.append(season)

    frames = historical
    if REPLAY_DATA.is_file():
        holdout = pd.read_csv(REPLAY_DATA)
        extra_columns = [column for column in ["Team", "TyreLife", "Compound", "FreshTyre", "TrackTemp", "AirTemp"] if column not in holdout.columns]
        if extra_columns:
            race_metadata = source[["Year", "Round", "Driver", "LapNumber", *extra_columns]].drop_duplicates(
                ["Year", "Round", "Driver", "LapNumber"], keep="last"
            )
            holdout = holdout.merge(race_metadata, on=["Year", "Round", "Driver", "LapNumber"], how="left")
        if "LapSeconds" not in holdout.columns:
            holdout["LapSeconds"] = holdout["CurrentLapSeconds"]
        if "NextLapSeconds" not in holdout.columns:
            holdout["NextLapSeconds"] = holdout["ActualNextLapSeconds"]
        year = int(holdout["Year"].dropna().iloc[0])
        model, training_rows = _fit_replay_model(pd, source[source["Year"] < year])
        if model is None or any(col not in holdout for col in MODEL_REQUIRED):
            holdout["MLPrediction"] = float("nan")
            holdout["MLAbsError"] = float("nan")
        else:
            ready = holdout.dropna(subset=MODEL_REQUIRED).copy()
            prepared = _model_features(pd, ready)
            holdout["MLPrediction"] = float("nan")
            holdout.loc[ready.index, "MLPrediction"] = ready["LapSeconds"] + model.predict(prepared[MODEL_CAT + MODEL_NUM])
            holdout["MLAbsError"] = (holdout["ActualNextLapSeconds"] - holdout["MLPrediction"]).abs()
        holdout["MLTrainingRows"] = training_rows
        frames.append(holdout)
    if not frames:
        raise ValueError("No replay seasons are available in the project data.")
    return pd.concat(frames, ignore_index=True, sort=False)

_replay_cache = None

class WatchManager:
    def __init__(self, log_path):
        self.log_path = log_path
        self.lock = threading.Lock()
        self.stop_event = None
        self.thread = None
        self.state = {"running": False, "session_key": None, "driver_number": None, "interval": None, "message": "Stopped", "last_result": None, "updated": None}

    def status(self):
        with self.lock:
            return dict(self.state)

    def start(self, session_key, driver_number, interval):
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise ValueError("A watch is already running.")
            self.stop_event = threading.Event()
            self.state = {"running": True, "session_key": session_key, "driver_number": driver_number, "interval": interval, "message": "Starting…", "last_result": None, "updated": None}
            self.thread = threading.Thread(target=self._run, args=(session_key, driver_number, interval, self.stop_event), daemon=True)
            self.thread.start()

    def stop(self):
        with self.lock:
            if self.stop_event:
                self.stop_event.set()
            self.state["running"] = False
            self.state["message"] = "Stopping watch…"

    def _run(self, session_key, driver_number, interval, event):
        while not event.is_set():
            try:
                result = predict_live(session_key, driver_number, self.log_path)
                message = f"Lap {result['lap_number']} forecast ready: {result['predicted_seconds']:.3f} s"
                with self.lock:
                    self.state.update(message=message, last_result=result, updated=time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()))
            except Exception as exc:
                with self.lock:
                    self.state.update(message=str(exc), updated=time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()))
                if "chequered flag" in str(exc).casefold():
                    event.set()
            event.wait(interval)
        with self.lock:
            self.state["running"] = False
            if self.state["message"] == "Stopping watch…":
                self.state["message"] = "Stopped"


def read_history(db_path, limit=100):
    if not db_path.exists():
        return {"total": 0, "scored": 0, "mae": None, "rows": []}
    with sqlite3.connect(db_path, timeout=5) as db:
        db.row_factory = sqlite3.Row
        total = db.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
        scored, mae = db.execute("SELECT COUNT(absolute_error_seconds), AVG(absolute_error_seconds) FROM predictions WHERE absolute_error_seconds IS NOT NULL").fetchone()
        rows = [dict(row) for row in db.execute("SELECT * FROM predictions ORDER BY prediction_utc DESC LIMIT ?", (limit,))]
    return {"total": total, "scored": scored, "mae": mae, "rows": rows}

class Handler(BaseHTTPRequestHandler):
    manager = None
    log_path = None

    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))

    def _json(self, value, status=200):
        body = json.dumps(value, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        route = urlparse(self.path).path
        if route == "/api/status":
            return self._json(self.manager.status())
        if route in ("/api/replay/options", "/api/replay/data"):
            try:
                import pandas as pd
                global _replay_cache
                if _replay_cache is None:
                    _replay_cache = _build_replay_cache(pd)
                data = _replay_cache
                required = {"Year", "Round", "Circuit", "Driver", "LapNumber", "CurrentLapSeconds", "ActualNextLapSeconds", "PersistencePrediction", "PersistenceAbsError", "CircuitPrediction", "CircuitAbsError"}
                missing = required - set(data.columns)
                if missing:
                    raise ValueError("Replay file is missing fields: " + ", ".join(sorted(missing)))
                query = parse_qs(urlparse(self.path).query)
                year = int(query.get("year", [int(data["Year"].max())])[0])
                season = data[data["Year"] == year]
                if season.empty:
                    return self._json({"error": f"No replay data for season {year}."}, 404)
                races = season[["Round", "Circuit"]].drop_duplicates().sort_values("Round")
                round_number = int(query.get("round", [int(races.iloc[0]["Round"])])[0])
                race = season[season["Round"] == round_number]
                if race.empty:
                    return self._json({"error": f"No replay data for {year} Round {round_number}."}, 404)
                if route == "/api/replay/options":
                    driver_rows = race[["Driver", "Team"]].copy()
                    driver_rows["Driver"] = driver_rows["Driver"].astype(str).str.upper()
                    driver_rows = driver_rows.drop_duplicates("Driver").set_index("Driver")
                    return self._json({
                        "years": sorted(int(y) for y in data["Year"].dropna().unique()),
                        "races": [{"round": int(row.Round), "circuit": str(row.Circuit), "country_code": RACE_COUNTRY_CODES.get(str(row.Circuit).strip().casefold(), ""), "circuit_svg": circuit_svg_url(row.Circuit)} for row in races.itertuples(index=False)],
                        "drivers": [replay_driver_data(code, year, str(driver_rows.loc[code, "Team"])) for code in sorted(driver_rows.index)],
                        "has_ml_model": bool(race.get("MLPrediction", pd.Series(dtype=float)).notna().any()),
                        "ml_training_rows": int(race["MLTrainingRows"].max()) if "MLTrainingRows" in race and race["MLTrainingRows"].notna().any() else 0,
                        "year": year, "round": round_number,
                    })
                if not query.get("driver") or not query["driver"][0].strip():
                    return self._json({"error": "Select a driver for this season and race."}, 400)
                driver = str(query["driver"][0]).upper()
                valid_drivers = set(race["Driver"].dropna().astype(str).str.upper())
                if driver not in valid_drivers:
                    return self._json({"error": f"{driver} did not race in {year} Round {round_number}. Select a valid driver."}, 404)
                selected = race[race["Driver"].astype(str) == driver].sort_values("LapNumber")
                if selected.empty:
                    return self._json({"error": f"No replay laps found for {driver}."}, 404)
                columns = ["LapNumber", "CurrentLapSeconds", "ActualNextLapSeconds", "PersistencePrediction", "PersistenceAbsError", "CircuitPrediction", "CircuitAbsError", "MLPrediction", "MLAbsError", "MLTrainingRows", "TyreLife"]
                selected_rows = selected[[column for column in columns if column in selected.columns]].copy()
                if "TyreLife" not in selected_rows.columns:
                    selected_rows["TyreLife"] = None
                rows = selected_rows.astype(object).where(pd.notna(selected_rows), None).to_dict(orient="records")
                return self._json({
                    "year": year, "round": round_number, "circuit": str(selected.iloc[0]["Circuit"]),
                    "circuit_svg": circuit_svg_url(selected.iloc[0]["Circuit"]),
                    "driver": driver, "rows": rows,
                    "metrics": {"persistence_mae": float(selected["PersistenceAbsError"].mean()), "circuit_mae": float(selected["CircuitAbsError"].mean()), "ml_mae": float(selected["MLAbsError"].mean()) if "MLAbsError" in selected and selected["MLAbsError"].notna().any() else None, "ml_prediction_rows": int(selected["MLPrediction"].notna().sum()) if "MLPrediction" in selected else 0, "laps": int(len(selected))},
                })
            except (ValueError, TypeError, FileNotFoundError) as exc:
                return self._json({"error": str(exc)}, 400)
            except Exception as exc:
                return self._json({"error": f"Could not load historical replay: {exc}"}, 500)
        if route == "/api/drivers":
            try:
                requested = parse_qs(urlparse(self.path).query).get("session_key", ["latest"])[0]
                import pandas as pd
                info = resolve_session(requested, pd.Timestamp.now(tz="UTC"))
                session_type = str(info.get("session_type", info.get("session_name", ""))).strip().casefold()
                if session_type != "race":
                    return self._json({"error": "Choose a Race session to load its driver list."}, 400)
                session_id = info.get("session_key", requested)
                drivers = get_frame("drivers", session_key=session_id)
                if drivers.empty:
                    return self._json({"error": "OpenF1 has no driver roster for this session yet."}, 404)
                def field(row, key):
                    value = row.get(key)
                    return "" if value is None or pd.isna(value) else str(value)

                season_value = pd.to_numeric(info.get("year"), errors="coerce")
                season_year = int(season_value) if pd.notna(season_value) else 0
                records = []
                for _, row in drivers.iterrows():
                    acronym = field(row, "name_acronym").upper()
                    name = field(row, "full_name") or field(row, "broadcast_name") or acronym or "Driver"
                    team_name = field(row, "team_name") or "Unknown team"
                    hero_url = season_driver_hero_url(acronym, team_name, season_year)
                    headshot_url = field(row, "headshot_url")
                    headshot_url = headshot_url.replace("/d_driver_fallback_image.png/content/dam/", "/content/dam/")
                    headshot_url = headshot_url.replace(".png.transform/1col/image.png", ".png")
                    records.append({
                        "driver_number": int(row["driver_number"]),
                        "name": name,
                        "acronym": acronym,
                        "country_code": field(row, "country_code"),
                        "team_name": team_name,
                        "team_colour": field(row, "team_colour") or TEAM_COLOURS.get(team_name.casefold(), "465365"),
                        "team_logo_url": team_logo_url(team_name, season_year),
                        "car_image_url": team_car_url(team_name, season_year),
                        "headshot_url": headshot_url,
                        "hero_url": hero_url,
                    })
                return self._json({"session_key": session_id, "year": info.get("year"), "circuit": str(info.get("circuit_short_name") or ""), "drivers": records})
            except RuntimeError as exc:
                return self._json({"error": str(exc)}, 404)
            except Exception as exc:
                return self._json({"error": f"Could not load driver list: {exc}"}, 502)
        if route.startswith("/demo-data/"):
            filename = route.removeprefix("/demo-data/")
            demo_root = (WEB / "demo-data").resolve()
            path = (demo_root / filename).resolve()
            if not path.is_relative_to(demo_root) or path.suffix != ".json" or not path.is_file():
                return self.send_error(404)
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            return self.wfile.write(body)
        if route.startswith("/assets/"):
            filename = route.removeprefix("/assets/")
            if filename in {"icon.png", "logo.png", "Formula1-Bold_web_0.ttf", "f1-mark.svg"}:
                path = WEB / "assets" / filename
            elif filename.startswith("circuits/") and Path(filename).name == filename.split("/")[-1] and filename.endswith(".svg"):
                path = WEB / "assets" / "circuits" / Path(filename).name
            else:
                return self.send_error(404)
            if not path.is_file():
                return self.send_error(404)
            content_type = "font/ttf" if filename.endswith(".ttf") else "image/svg+xml" if filename.endswith(".svg") else "image/png"
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            return self.wfile.write(body)
        if route == "/api/history":
            try:
                limit = max(1, min(500, int(parse_qs(urlparse(self.path).query).get("limit", [100])[0])))
                return self._json(read_history(self.log_path, limit))
            except (ValueError, sqlite3.Error) as exc:
                return self._json({"error": str(exc)}, 500)
        if route in ("/", "/index.html"):
            path = WEB / "index.html"
            if not path.is_file():
                return self.send_error(404)
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        return self.send_error(404)

    def do_POST(self):
        route = urlparse(self.path).path
        if route == "/api/watch/stop":
            self.manager.stop()
            return self._json({"ok": True})
        if route == "/api/watch/start":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                data = json.loads(self.rfile.read(length))
                session_key = str(data.get("session_key", "latest")).strip() or "latest"
                driver = int(data.get("driver_number", 1))
                interval = int(data.get("interval", 30))
                if driver < 1 or interval < 5:
                    raise ValueError("Driver number must be positive and interval at least 5 seconds.")
                self.manager.start(session_key, driver, interval)
                return self._json({"ok": True}, 202)
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                return self._json({"error": str(exc)}, 400)
        return self.send_error(404)

    def do_OPTIONS(self):
        return self.send_error(405)


def main():
    parser = argparse.ArgumentParser(description="Serve the local F1 prediction dashboard.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: localhost only)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG_DB)
    args = parser.parse_args()
    Handler.manager = WatchManager(args.log)
    Handler.log_path = args.log
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"F1 predictor dashboard: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        Handler.manager.stop()
        server.server_close()

if __name__ == "__main__":
    main()
