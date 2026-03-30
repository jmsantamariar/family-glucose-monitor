"""Main entry point for family glucose monitoring."""
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


def run_once(config: dict) -> None:
    state_path = config.get("state_file", "state.json")
    if not os.path.isabs(state_path):
        state_path = str(PROJECT_ROOT / state_path)
    state = load_state(state_path)
    readings = read_all_patients(config)
    if not readings:
        logger.error("No readings obtained from any patient")
        return
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
                clear_patient_state(state, patient_id)
                state_changed = True
            continue
        if not should_alert(level, patient_state, cooldown):
            logger.info("  Cooldown active for %s (%s), skipping", patient_name, level)
            continue
        message = build_message(glucose_value, level, trend_arrow, patient_name=patient_name, config=config)
        sent_any = False
        for output in outputs:
            try:
                if output.send_alert(message, glucose_value, level):
                    sent_any = True
            except Exception as e:
                logger.error("Output %s failed: %s", type(output).__name__, e)
        if sent_any:
            now_iso = datetime.now(timezone.utc).isoformat()
            set_patient_state(state, patient_id, {
                "last_alert_time": now_iso,
                "last_alert_level": level,
                "last_glucose_value": glucose_value,
            })
            state_changed = True
            logger.info("  Alert sent for %s: %s (%d mg/dL)", patient_name, level, glucose_value)
    if state_changed:
        save_state(state_path, state)


def main() -> None:
    config_path = os.environ.get("CONFIG_PATH", str(PROJECT_ROOT / "config.yaml"))
    if not os.path.exists(config_path):
        print(f"Config file not found: {config_path}", file=sys.stderr)
        print("Copy config.example.yaml to config.yaml and fill in your values.", file=sys.stderr)
        sys.exit(1)
    with open(config_path) as f:
        config = yaml.safe_load(f)
    configure_logging(config)
    error = validate_config(config)
    if error:
        logger.error("Configuration error: %s", error)
        sys.exit(1)
    lock_path = config.get("lock_file", "/tmp/family-glucose-monitor.lock")
    lock_fd = acquire_lock(lock_path)
    try:
        mode = config.get("monitoring", {}).get("mode", "cron")
        if mode == "daemon":
            interval = config.get("monitoring", {}).get("interval_seconds", 300)
            logger.info("Running in daemon mode, interval: %ds", interval)
            while True:
                try:
                    run_once(config)
                except Exception as e:
                    logger.error("Error in monitoring cycle: %s", e)
                time.sleep(interval)
        else:
            run_once(config)
    finally:
        release_lock(lock_fd)


if __name__ == "__main__":
    main()
