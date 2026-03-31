"""FastAPI web server for the glucose monitoring dashboard and REST API."""
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from src import alert_engine
from src.alert_history import get_alerts
from src.glucose_reader import read_all_patients

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# In-memory cache of latest readings per patient
_readings_cache: dict = {}
_cache_lock = threading.Lock()
_config: dict = {}


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


@asynccontextmanager
async def lifespan(application: "FastAPI"):
    global _config
    try:
        _config = load_config()
    except FileNotFoundError:
        logger.warning("config.yaml not found, dashboard will start without polling")
    else:
        interval = _config.get("monitoring", {}).get("interval_seconds", 300)
        thread = threading.Thread(target=_poll_loop, args=(interval,), daemon=True)
        thread.start()
        logger.info("Background polling started every %d seconds", interval)
    yield


app = FastAPI(title="Family Glucose Monitor", version="1.0.0", lifespan=lifespan)


def _poll_loop(interval: int):
    """Background thread that polls LibreLinkUp and updates the cache."""
    while True:
        try:
            readings = read_all_patients(_config)
            with _cache_lock:
                for r in readings:
                    pid = r["patient_id"]
                    glucose = r["value"]
                    trend_arrow = r.get("trend_arrow", "")
                    level = alert_engine.evaluate(glucose, _config)
                    trend_alert = alert_engine.evaluate_trend(glucose, trend_arrow, _config)
                    r["glucose_value"] = glucose
                    r["level"] = level
                    r["trend_alert"] = trend_alert
                    r["color"] = _get_color(level, trend_alert)
                    r["fetched_at"] = datetime.now(timezone.utc).isoformat()
                    _readings_cache[pid] = r
            logger.info("Polled %d patients successfully", len(readings))
        except Exception as e:
            logger.error("Polling error: %s", e)
        time.sleep(interval)


def _get_color(level: str, trend_alert: str) -> str:
    """Return semaphore color: red, yellow, green."""
    if level in ("low", "high") or trend_alert == "falling_fast":
        return "red"
    if trend_alert in ("falling", "rising_fast"):
        return "yellow"
    return "green"


@app.get("/api/patients", response_class=JSONResponse)
def get_patients():
    """Return all patients with their latest readings."""
    with _cache_lock:
        patients = list(_readings_cache.values())
    return {"patients": patients, "count": len(patients)}


@app.get("/api/patients/{patient_id}", response_class=JSONResponse)
def get_patient(patient_id: str):
    """Return a specific patient's latest reading."""
    with _cache_lock:
        reading = _readings_cache.get(patient_id)
    if not reading:
        raise HTTPException(status_code=404, detail="Patient not found")
    return reading


@app.get("/api/health", response_class=JSONResponse)
def health_check():
    """Health check endpoint."""
    with _cache_lock:
        patient_count = len(_readings_cache)
    return {
        "status": "ok",
        "patients_monitored": patient_count,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/alerts", response_class=JSONResponse)
def get_alert_history(patient_id: Optional[str] = None, hours: int = 24):
    """Return alert history for the last *hours* hours.

    Optionally filter by *patient_id*.  Returns an empty list when there are no
    alerts or the database does not exist yet.
    """
    db_path = _config.get("alert_history_db", "alert_history.db")
    if not os.path.isabs(db_path):
        db_path = str(PROJECT_ROOT / db_path)
    alerts = get_alerts(db_path, patient_id=patient_id, hours=hours)
    return alerts


@app.get("/", response_class=HTMLResponse)
def dashboard():
    """Serve the dashboard HTML page."""
    html_path = Path(__file__).parent / "dashboard" / "index.html"
    if not html_path.exists():
        raise HTTPException(status_code=500, detail="Dashboard HTML not found")
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
