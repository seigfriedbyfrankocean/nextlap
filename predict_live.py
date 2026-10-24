"""Predict the next lap from OpenF1's latest completed race lap."""
import argparse
import sqlite3
import time
from pathlib import Path

import pandas as pd
import requests

from build_dataset_openf1_v3 import build_windows
from predict_next_lap import predict_next_lap

API = "https://api.openf1.org/v1"
DEFAULT_LOG_DB = Path(__file__).resolve().with_name("prediction_log.sqlite")


def get_frame(endpoint, **params):
    try:
        response = requests.get(f"{API}/{endpoint}", params=params, timeout=20)
    except requests.RequestException as exc:
        raise RuntimeError(f"OpenF1 request failed: {exc}") from exc

    if response.status_code == 404:
        return pd.DataFrame()
    if response.status_code == 429:
        raise RuntimeError("OpenF1 rate limit reached; retry in a little while.")
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise RuntimeError(f"OpenF1 returned HTTP {response.status_code} for {endpoint}.") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"OpenF1 returned invalid JSON for {endpoint}.") from exc
    if not isinstance(payload, list):
        raise RuntimeError(f"Unexpected response from OpenF1 {endpoint} endpoint.")
    return pd.DataFrame(payload)


def _is_wet(value):
    if isinstance(value, bool):
        return value
    if value is None or pd.isna(value):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"true", "t", "yes", "y"}
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def _neutral_state(control, now):
    """Replay the builder's event classifier to identify a still-active neutralisation."""
    from build_dataset_openf1_v3 import classify_event

    if control.empty or "date" not in control or "message" not in control:
        return None
    rc = control.copy()
    rc["date"] = pd.to_datetime(rc["date"], utc=True, format="mixed", errors="coerce")
    rc = rc.dropna(subset=["date"]).sort_values("date")
    rc = rc[rc["date"] <= now]
    flags = rc["flag"] if "flag" in rc.columns else pd.Series("", index=rc.index)

    state = None
    for message, flag in zip(rc["message"], flags):
        event = classify_event(message, flag)
        if event == "RED":
            state = "red flag"
        elif event == "SC_DEPLOY":
            state = "safety car"
        elif event == "VSC_DEPLOY":
            state = "virtual safety car"
        elif event == "SC_LIGHTS":
            state = "safety car"
        elif event == "SC_END" and state == "safety car":
            state = None
        elif event == "VSC_END" and state == "virtual safety car":
            state = None
        elif event == "RESTART" and state == "red flag":
            state = None
        elif event == "CHEQUERED":
            return "finished"
    return state


def resolve_session(session_key, now):
    """Resolve 'latest' to an active race; keep numeric session keys explicit."""
    if str(session_key).strip().casefold() == "latest":
        races = get_frame("sessions", year=now.year, session_type="Race")
        if not races.empty and {"date_start", "date_end"} <= set(races.columns):
            races = races.copy()
            races["date_start"] = pd.to_datetime(races["date_start"], utc=True, format="mixed", errors="coerce")
            races["date_end"] = pd.to_datetime(races["date_end"], utc=True, format="mixed", errors="coerce")
            active = races[(races["date_start"] <= now) & (races["date_end"] >= now)]
            if not active.empty:
                return active.sort_values("date_start").iloc[-1]

        latest = get_frame("sessions", session_key="latest")
        if latest.empty:
            raise RuntimeError("OpenF1 has no current session record, and no Race session is underway.")
        row = latest.iloc[-1]
        name = str(row.get("session_name", row.get("session_type", "session")))
        circuit = str(row.get("circuit_short_name", "unknown circuit"))
        end = pd.to_datetime(row.get("date_end"), utc=True, format="mixed", errors="coerce")
        ended = f"; it ended at {end.strftime('%Y-%m-%d %H:%M UTC')}" if pd.notna(end) and end < now else ""
        raise RuntimeError(f"No Race session is live right now. OpenF1's latest session is {name} at {circuit}{ended}.")

    session = get_frame("sessions", session_key=session_key)
    if session.empty:
        raise RuntimeError(f"No session found for session_key={session_key}.")
    return session.iloc[-1]

def _open_log(log_path):
    connection = sqlite3.connect(log_path, timeout=10)
    connection.execute(
        """CREATE TABLE IF NOT EXISTS predictions (
            session_key TEXT NOT NULL,
            driver_number INTEGER NOT NULL,
            origin_lap INTEGER NOT NULL,
            prediction_utc TEXT NOT NULL,
            circuit TEXT NOT NULL,
            driver TEXT NOT NULL,
            current_lap_seconds REAL NOT NULL,
            predicted_next_lap_seconds REAL NOT NULL,
            actual_next_lap_seconds REAL,
            absolute_error_seconds REAL,
            status TEXT NOT NULL DEFAULT 'pending',
            PRIMARY KEY (session_key, driver_number, origin_lap)
        )"""
    )
    connection.commit()
    return connection


def _reconcile_log(log_path, session_key, driver_number, completed_laps):
    connection = _open_log(log_path)
    for row in completed_laps.itertuples(index=False):
        if pd.isna(row.lap_number) or pd.isna(row.lap_duration):
            continue
        target_lap = int(row.lap_number)
        connection.execute(
            """UPDATE predictions
               SET actual_next_lap_seconds = ?,
                   absolute_error_seconds = ABS(predicted_next_lap_seconds - ?),
                   status = 'scored'
               WHERE session_key = ? AND driver_number = ? AND origin_lap = ?
                 AND actual_next_lap_seconds IS NULL""",
            (float(row.lap_duration), float(row.lap_duration), str(session_key), int(driver_number), target_lap - 1),
        )
    connection.commit()
    connection.close()


def _record_prediction(log_path, result):
    connection = _open_log(log_path)
    connection.execute(
        """INSERT OR IGNORE INTO predictions (
            session_key, driver_number, origin_lap, prediction_utc, circuit, driver,
            current_lap_seconds, predicted_next_lap_seconds, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
        (
            str(result["session_key"]), int(result["driver_number"]), int(result["lap_number"]),
            pd.Timestamp.now(tz="UTC").isoformat(), result["circuit"], result["driver"],
            float(result["lap_seconds"]), float(result["predicted_seconds"]),
        ),
    )
    connection.commit()
    connection.close()

def predict_live(session_key, driver_number, log_path=None):
    """Fetch live context, reject out-of-scope conditions, then return a baseline forecast."""
    now = pd.Timestamp.now(tz="UTC")
    info = resolve_session(session_key, now)
    session_type = str(info.get("session_type", info.get("session_name", ""))).strip().casefold()
    if session_type != "race":
        raise RuntimeError(f"This model is trained for race laps; this is a {session_type or 'non-race'} session.")
    session_id = info.get("session_key", session_key)

    laps = get_frame("laps", session_key=session_id, driver_number=driver_number)
    if laps.empty:
        raise RuntimeError("No lap records are available for this driver in the session yet.")
    laps["lap_duration"] = pd.to_numeric(laps.get("lap_duration"), errors="coerce")
    laps["lap_number"] = pd.to_numeric(laps.get("lap_number"), errors="coerce")
    completed = laps.dropna(subset=["lap_duration", "lap_number"]).copy()
    completed = completed[completed["lap_duration"] > 0]
    if log_path is not None:
        _reconcile_log(log_path, session_id, driver_number, completed)
    if completed.empty:
        raise RuntimeError("No completed lap with a valid time is available yet.")
    completed = completed.sort_values(["lap_number", "date_start"])
    lap = completed.iloc[-1]
    lap_number = int(lap["lap_number"])
    lap_seconds = float(lap["lap_duration"])
    if lap_number <= 1:
        raise RuntimeError("Lap 1 is excluded from the training data; wait for another completed lap.")
    if _is_wet(lap.get("is_pit_out_lap")):
        raise RuntimeError("The latest completed lap is a pit-out lap, which this baseline excludes.")

    circuit = str(info.get("circuit_short_name", "")).strip()
    if not circuit:
        raise RuntimeError("OpenF1 did not provide a circuit name for this session.")
    drivers = get_frame("drivers", session_key=session_id, driver_number=driver_number)
    driver_name = str(drivers.iloc[0].get("full_name") or drivers.iloc[0].get("broadcast_name") or drivers.iloc[0].get("name_acronym") or f"Driver #{driver_number}") if not drivers.empty else f"Driver #{driver_number}"

    control = get_frame("race_control", session_key=session_id)
    neutral = _neutral_state(control, now)
    lap_start = pd.to_datetime(lap.get("date_start"), utc=True, errors="coerce")
    if pd.isna(lap_start):
        raise RuntimeError("OpenF1 did not provide a start time for the latest completed lap.")
    lap_end = lap_start + pd.to_timedelta(lap_seconds, unit="s")
    for window in build_windows(control, now):
        if lap_start < window["end"] and lap_end > window["start"]:
            raise RuntimeError(
                f"The latest lap overlapped a {window['kind']} period; "
                "this baseline is for green-flag laps."
            )
    if neutral == "finished":
        raise RuntimeError("The race has reached the chequered flag; no next-lap prediction is available.")
    if neutral:
        raise RuntimeError(f"The session is under {neutral}; this baseline is for green-flag laps.")

    pit = get_frame("pit", session_key=session_id, driver_number=driver_number)
    if not pit.empty and "lap_number" in pit.columns:
        pit_laps = pd.to_numeric(pit["lap_number"], errors="coerce")
        if (pit_laps == lap_number).any():
            raise RuntimeError("The latest completed lap is a pit-in lap, which this baseline excludes.")

    weather = get_frame("weather", session_key=session_id)
    if weather.empty or "date" not in weather.columns or "rainfall" not in weather.columns:
        raise RuntimeError("Current weather is unavailable, so a dry-lap prediction cannot be confirmed.")
    weather["date"] = pd.to_datetime(weather["date"], utc=True, format="mixed", errors="coerce")
    weather = weather.dropna(subset=["date"]).sort_values("date")
    weather = weather[weather["date"] <= now]
    if weather.empty:
        raise RuntimeError("Current weather is unavailable, so a dry-lap prediction cannot be confirmed.")
    latest_weather = weather.iloc[-1]
    age_minutes = (now - latest_weather["date"]).total_seconds() / 60
    if age_minutes > 10:
        raise RuntimeError(f"The latest weather reading is {age_minutes:.0f} minutes old; dry conditions cannot be confirmed.")
    if _is_wet(latest_weather["rainfall"]):
        raise RuntimeError("Rain is reported for this session; the baseline was trained on dry races.")

    predicted, delta, source, count = predict_next_lap(circuit, lap_seconds)
    result = {
        "circuit": circuit,
        "session_key": session_id,
        "driver": driver_name,
        "driver_number": int(driver_number),
        "lap_number": lap_number,
        "lap_seconds": lap_seconds,
        "predicted_seconds": predicted,
        "delta_seconds": delta,
        "baseline_source": source,
        "training_rows": count,
    }
    if log_path is not None:
        _record_prediction(log_path, result)
    return result


def _print_result(result):
    print(f"{result['circuit']} | {result['driver']} #{result['driver_number']} | lap {result['lap_number']}")
    print(f"Latest completed lap: {result['lap_seconds']:.3f} s")
    print(f"Predicted next lap: {result['predicted_seconds']:.3f} s")
    details = f"; {result['training_rows']} training rows" if result["training_rows"] else ""
    print(f"Adjustment: {result['delta_seconds']:+.3f} s ({result['baseline_source']}{details})")
    print("Scope: estimate for a dry, green-flag race lap; a planned pit stop is not forecast.")


def watch(session_key, driver_number, interval, log_path):
    print(f"Watching {session_key} for driver #{driver_number}; checking every {interval} seconds. Press Ctrl+C to stop.")
    last_lap = None
    last_status = None
    try:
        while True:
            try:
                result = predict_live(session_key, driver_number, log_path)
                lap_key = (result["session_key"], result["lap_number"])
                if lap_key != last_lap:
                    print()
                    _print_result(result)
                    last_lap = lap_key
                last_status = None
            except RuntimeError as exc:
                status = str(exc)
                if "chequered flag" in status.casefold():
                    print(f"Race finished: {status}")
                    return
                if status != last_status:
                    print(f"Waiting: {status}")
                    last_status = status
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nWatch stopped.")


def main():
    parser = argparse.ArgumentParser(
        description="Predict next-lap times from OpenF1 race data."
    )
    parser.add_argument("session_key", help="OpenF1 race session key, or 'latest'")
    parser.add_argument("driver_number", type=int, help="Driver number in that session")
    parser.add_argument("--watch", action="store_true", help="Keep checking and predict once per new eligible lap")
    parser.add_argument("--interval", type=int, default=30, help="Watch polling interval in seconds (minimum 5; default 30)")
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG_DB, help="SQLite forecast log (default: prediction_log.sqlite)")
    args = parser.parse_args()
    if args.interval < 5:
        parser.error("--interval must be at least 5 seconds")

    if args.watch:
        watch(args.session_key, args.driver_number, args.interval, args.log)
        return

    try:
        result = predict_live(args.session_key, args.driver_number, args.log)
    except RuntimeError as exc:
        parser.exit(2, f"No prediction: {exc}\n")
    _print_result(result)


if __name__ == "__main__":
    main()