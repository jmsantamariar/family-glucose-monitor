"""Main entry point for family glucose monitoring."""
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent

from src.alert_engine import build_message, evaluate, is_stale, should_alert
from src.glucose_reader import read_all_patients
from src.outputs.telegram import TelegramOutput
from src.outputs.webhook import WebhookOutput
from src.outputs.whatsapp import WhatsAppOutput
from src.state import (
    clear_patient_state,
    get_patient_state,
    load_state,
    save_state,
    set_patient_state,
)

logger = logging.getLogger("family-glucose-monitor")


def validate_config(config: dict) -> str | None:
    try:
        alerts = config["alerts"]
        low = alerts["low_threshold"]
        high = alerts["high_threshold"]
    except KeyError as e:
        return f"Missing required config field: {e}"
    if not isinstance(low, (int, float)) or not isinstance(high, (int, float)):
        return "Thresholds must be numbers"
    if low <= 0 or high <= 0:
        return "Thresholds must be positive"
    if low >= high:
        return f"low_threshold ({low}) must be less than high_threshold ({high})"
    cooldown = alerts.get("cooldown_minutes")
    if cooldown is None or cooldown <= 0:
        return "cooldown_minutes must be a positive number"
    max_age = alerts.get("max_reading_age_minutes")
    if max_age is None or max_age <= 0:
        return "max_reading_age_minutes must be a positive number"
    if "librelinkup" not in config:
        return "Missing librelinkup config section"
    ll = config["librelinkup"]
    if not ll.get("email") and not os.environ.get("LIBRELINKUP_EMAIL"):
        return "Missing librelinkup email (set in config or LIBRELINKUP_EMAIL env var)"
    if not ll.get("password") and not os.environ.get("LIBRELINKUP_PASSWORD"):
        return "Missing librelinkup password (set in config or LIBRELINKUP_PASSWORD env var)"
    return None


def configure_logging(config: dict) -> None:
    log_config = config.get("logging", {})
    level = getattr(logging, log_config.get("level", "INFO").upper(), logging.INFO)
    log_file = log_config.get("file", "")
    handler: logging.Handler
    if log_file:
        handler = logging.FileHandler(log_file)
    else:
        handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)


def build_outputs(config: dict) -> list:
    outputs = []
    for out_cfg in config.get("outputs", []):
        if not out_cfg.get("enabled", False):
            continue
        out_type = out_cfg.get("type")
        if out_type == "webhook":
            outputs.append(WebhookOutput(
                url=out_cfg["url"],
                token=out_cfg.get("token", ""),
                device=out_cfg.get("device", ""),
                language=out_cfg.get("language", ""),
            ))
        elif out_type == "whatsapp":
            access_token = os.environ.get("WHATSAPP_ACCESS_TOKEN") or out_cfg.get("access_token", "")
            outputs.append(WhatsAppOutput(
                phone_number_id=out_cfg["phone_number_id"],
                access_token=access_token,
                recipient=out_cfg["recipient"],
                template_name=out_cfg.get("template_name", "glucose_alert"),
                language_code=out_cfg.get("language_code", "es_MX"),
            ))
        elif out_type == "telegram":
            outputs.append(TelegramOutput(
                bot_token=out_cfg["bot_token"],
                chat_id=out_cfg["chat_id"],
            ))
        else:
            logger.warning("Unknown output type '%s', skipping", out_type)
    return outputs


def acquire_lock(lock_path: str):
    try:
        import fcntl
        lock_fd = open(lock_path, "w")
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock_fd
    except ImportError:
        logger.debug("fcntl not available, skipping file lock")
        return None
    except OSError:
        logger.info("Another instance is running, exiting")
        sys.exit(0)


def release_lock(lock_fd) -> None:
    if lock_fd is None:
        return
    try:
        import fcntl
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()
    except ImportError:
        pass


def _save_readings_cache(readings: list[dict], config: dict) -> None:
    """Write the latest readings to readings_cache.json for API consumption."""
    cache_path = config.get("api", {}).get("cache_file", "readings_cache.json")
    if not os.path.isabs(cache_path):
        cache_path = str(PROJECT_ROOT / cache_path)
    payload = {
        "readings": readings,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    tmp_path = cache_path + ".tmp"
    try:
        with open(tmp_path, "w") as f:
            json.dump(payload, f, default=str)
        os.replace(tmp_path, cache_path)
        logger.debug("Readings cache saved to %s", cache_path)
    except OSError as e:
        logger.error("Failed to save readings cache: %s", e)


def run_once(config: dict) -> None:
    state_path = config.get("state_file", "state.json")
    if not os.path.isabs(state_path):
        state_path = str(PROJECT_ROOT / state_path)
    state = load_state(state_path)
    readings = read_all_patients(config)
    if not readings:
        logger.error("No readings obtained from any patient")
        return
    _save_readings_cache(readings, config)
    max_age = config["alerts"]["max_reading_age_minutes"]
    cooldown = config["alerts"]["cooldown_minutes"]
    outputs = build_outputs(config)
    if not outputs:
        logger.warning("No outputs enabled, cannot send alerts")
    state_changed = False
    for reading in readings:
        patient_id = reading["patient_id"]
        patient_name = reading["patient_name"]
        glucose_value = reading["value"]
        timestamp = reading["timestamp"]
        trend_arrow = reading["trend_arrow"]
        logger.info("  %s: %d mg/dL %s (%s)", patient_name, glucose_value, trend_arrow, timestamp)
        if is_stale(timestamp, max_age):
            logger.warning("  Stale reading for %s from %s, skipping", patient_name, timestamp)
            continue
        level = evaluate(glucose_value, config)
        patient_state = get_patient_state(state, patient_id)
        if level == "normal":
            if patient_state:
                state = clear_patient_state(state, patient_id)
                state_changed = True
                logger.info("  %s back to normal, state cleared", patient_name)
            else:
                logger.info("  %s normal", patient_name)
            continue
        if not outputs:
            continue
        if not should_alert(level, patient_state, cooldown):
            logger.info("  %s alert suppressed by cooldown", patient_name)
            continue
        message = build_message(glucose_value, level, trend_arrow, patient_name, config)
        any_success = False
        for output in outputs:
            try:
                if output.send_alert(message, glucose_value, level):
                    any_success = True
            except Exception as e:
                logger.error("Output %s failed: %s", type(output).__name__, e)
        if any_success:
            new_patient_state = {
                "last_alert_time": datetime.now(timezone.utc).isoformat(),
                "last_alert_level": level,
            }
            state = set_patient_state(state, patient_id, new_patient_state)
            state_changed = True
            logger.info("  Alert sent for %s: %s", patient_name, message)
        else:
            logger.error("  All outputs failed for %s, state not updated", patient_name)
    if state_changed:
        save_state(state_path, state)


def main() -> None:
    config_path = PROJECT_ROOT / "config.yaml"
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        print(
            f"ERROR: {config_path} not found. Copy config.example.yaml to config.yaml",
            file=sys.stderr,
        )
        sys.exit(1)
    if config is None:
        print("ERROR: config.yaml is empty", file=sys.stderr)
        sys.exit(1)
    configure_logging(config)
    error = validate_config(config)
    if error:
        logger.error("Config validation failed: %s", error)
        sys.exit(1)
    lock_path = config.get("lock_file", "/tmp/family-glucose-monitor.lock")
    if not os.path.isabs(lock_path):
        lock_path = str(PROJECT_ROOT / lock_path)
    lock_fd = acquire_lock(lock_path)
    try:
        mode = config.get("monitoring", {}).get("mode", "cron")
        if mode == "daemon":
            interval = config.get("monitoring", {}).get("interval_seconds", 300)
            logger.info("Starting in daemon mode (interval: %ds)", interval)
            while True:
                try:
                    run_once(config)
                except Exception as e:
                    logger.error("Error in monitoring cycle: %s: %s", type(e).__name__, e)
                logger.info("Sleeping %d seconds...", interval)
                time.sleep(interval)
        else:
            run_once(config)
    finally:
        release_lock(lock_fd)


if __name__ == "__main__":
    main()
