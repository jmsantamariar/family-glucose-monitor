"""Main entry point for family glucose monitoring."""
import json
import logging
import os
import stat
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent

from src.alert_engine import build_message, evaluate, evaluate_trend, is_stale, should_alert
from src.alert_history import cleanup_old_alerts, init_db, log_alert
from src.config_schema import validate_config as schema_validate_config
from src.glucose_reader import read_all_patients
from src.outputs import build_outputs
from src.outputs.base import Notifier
from src.outputs.multi_notifier import MultiNotifier
from src.setup_status import check_setup
from src.state import (
    clear_patient_state,
    get_patient_state,
    load_state,
    save_state,
    set_patient_state,
)

logger = logging.getLogger("family-glucose-monitor")


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
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(handler)


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


def run_once(
    config: dict,
    outputs: list | None = None,
    notifier: Notifier | None = None,
) -> None:
    """Execute one monitoring cycle: read → evaluate → alert → persist.

    Parameters
    ----------
    config:
        Validated application configuration dictionary.
    outputs:
        *Deprecated convenience parameter.*  When supplied, the list is
        wrapped in a :class:`~src.outputs.multi_notifier.MultiNotifier` and
        used as the notifier.  Ignored when *notifier* is also provided.
    notifier:
        A :class:`~src.outputs.base.Notifier` instance responsible for
        dispatching alerts.  When *None* (default), one is built from the
        enabled outputs in *config* (or from *outputs* if supplied).

    Passing a pre-built *notifier* (or the legacy *outputs* list) allows
    long-running modes (``daemon``, ``full``) to construct the outputs once
    and reuse them across every polling cycle without re-reading config.
    """
    state_path = config.get("state_file", "state.json")
    if not os.path.isabs(state_path):
        state_path = str(PROJECT_ROOT / state_path)

    db_path = config.get("alert_history_db", "alert_history.db")
    if not os.path.isabs(db_path):
        db_path = str(PROJECT_ROOT / db_path)
    init_db(db_path)

    state = load_state(state_path)
    readings = read_all_patients(config)
    if not readings:
        logger.error("No readings obtained from any patient")
        return
    _save_readings_cache(readings, config)
    max_age = config["alerts"]["max_reading_age_minutes"]
    cooldown = config["alerts"]["cooldown_minutes"]

    # Resolve the notifier to use for this cycle.
    if notifier is None:
        _raw_outputs = outputs if outputs is not None else build_outputs(config)
        notifier = MultiNotifier(_raw_outputs)
    if not notifier:
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
        trend_alert = evaluate_trend(glucose_value, trend_arrow, config)
        patient_state = get_patient_state(state, patient_id)
        if level == "normal" and trend_alert == "normal":
            if patient_state:
                state = clear_patient_state(state, patient_id)
                state_changed = True
                logger.info("  %s back to normal, state cleared", patient_name)
            else:
                logger.info("  %s normal", patient_name)
            continue
        if not notifier:
            continue
        if not should_alert(level, patient_state, cooldown, trend_alert):
            logger.info("  %s alert suppressed by cooldown", patient_name)
            continue
        message = build_message(glucose_value, level, trend_arrow, patient_name, config, trend_alert)
        effective_level = level if level != "normal" else f"trend_{trend_alert}"
        if notifier.notify(message, glucose_value, level):
            new_patient_state = {
                "last_alert_time": datetime.now(timezone.utc).isoformat(),
                "last_alert_level": effective_level,
            }
            state = set_patient_state(state, patient_id, new_patient_state)
            state_changed = True
            log_alert(
                db_path,
                patient_id,
                patient_name,
                glucose_value,
                effective_level,
                trend_arrow,
                message,
            )
            logger.info("  Alert sent for %s: %s", patient_name, message)
        else:
            logger.error("  All outputs failed for %s, state not updated", patient_name)
    if state_changed:
        save_state(state_path, state)

    max_days = config.get("alert_history_max_days", 7)
    cleanup_old_alerts(db_path, max_days)


def _start_dashboard(config: dict) -> None:
    """Start the FastAPI dashboard server."""
    try:
        import uvicorn
    except ImportError:
        logger.error(
            "fastapi and uvicorn are required for dashboard mode. "
            "Run: pip install fastapi 'uvicorn[standard]'"
        )
        sys.exit(1)

    dash_cfg = config.get("dashboard", {})
    host = dash_cfg.get("host", "0.0.0.0")
    port = int(dash_cfg.get("port", 8080))
    logger.info("Starting dashboard on http://%s:%d", host, port)
    uvicorn.run("src.api:app", host=host, port=port, log_level="info")


def main() -> None:
    config_path = PROJECT_ROOT / "config.yaml"

    status = check_setup(config_path)
    if not status.complete:
        # No valid config — start in setup-only mode so the user can configure
        # the application through the web wizard at /setup.
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        for reason in status.errors:
            logger.warning("Setup required: %s", reason)
        logger.info(
            "Starting in setup-only mode. "
            "Visit http://0.0.0.0:8080/setup to complete configuration."
        )
        _start_dashboard({})
        return

    # Setup is complete — load the already-validated config.
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        # If the config file became unreadable or invalid after setup check,
        # fall back to setup-only mode instead of crashing.
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        logger.warning("Failed to load config after setup validation: %s", e)
        logger.info(
            "Starting in setup-only mode due to config load failure. "
            "Visit http://0.0.0.0:8080/setup to complete configuration."
        )
        _start_dashboard({})
        return

    configure_logging(config)
    # Ensure config.yaml permissions are restrictive (owner read/write only)
    try:
        current_mode = config_path.stat().st_mode
        if current_mode & (stat.S_IRGRP | stat.S_IROTH | stat.S_IWGRP | stat.S_IWOTH):
            os.chmod(config_path, stat.S_IRUSR | stat.S_IWUSR)
            logger.info("Restricted config.yaml permissions to 0600")
    except OSError:
        pass  # Windows or other OS without Unix permissions
    logger.info("Config validation passed")
    lock_path = config.get("lock_file", "/tmp/family-glucose-monitor.lock")
    if not os.path.isabs(lock_path):
        lock_path = str(PROJECT_ROOT / lock_path)
    mode = config.get("monitoring", {}).get("mode", "cron")

    if mode == "dashboard":
        _start_dashboard(config)
        return

    if mode == "full":
        lock_fd = acquire_lock(lock_path)
        try:
            from src.api import set_external_polling, update_readings_cache
            set_external_polling(True)
            interval = config.get("monitoring", {}).get("interval_seconds", 300)
            logger.info("Starting full mode (daemon + dashboard, interval: %ds)", interval)
            # Build the notifier once; it is reused across every polling cycle.
            _loop_notifier = MultiNotifier(build_outputs(config))

            def _polling_loop() -> None:
                while True:
                    try:
                        run_once(config, notifier=_loop_notifier)
                        update_readings_cache()
                    except Exception as e:
                        logger.error("Error in monitoring cycle: %s: %s", type(e).__name__, e)
                    time.sleep(interval)

            poll_thread = threading.Thread(target=_polling_loop, daemon=True)
            poll_thread.start()
            # Uvicorn runs on the main thread for proper signal handling
            _start_dashboard(config)
        finally:
            release_lock(lock_fd)
        return

    lock_fd = acquire_lock(lock_path)
    try:
        if mode == "daemon":
            interval = config.get("monitoring", {}).get("interval_seconds", 300)
            logger.info("Starting in daemon mode (interval: %ds)", interval)
            # Build the notifier once; it is reused across every polling cycle.
            _daemon_notifier = MultiNotifier(build_outputs(config))
            while True:
                try:
                    run_once(config, notifier=_daemon_notifier)
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
