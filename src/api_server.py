"""FastAPI REST API server for external consumption (widgets, dashboards, etc.)."""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from src.alert_history import get_alerts

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_FILE = PROJECT_ROOT / "readings_cache.json"
# Allow overriding the DB path via an environment variable so deployments can
# point to the same file used by main.py (which reads from config.yaml).
_default_db = str(PROJECT_ROOT / "alert_history.db")
DB_FILE = os.environ.get("ALERT_HISTORY_DB", _default_db)

app = FastAPI(
    title="Family Glucose Monitor API",
    description="REST API for external consumption of glucose readings (widgets, dashboards, etc.)",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _load_cache() -> dict:
    """Load the readings cache from disk. Returns empty structure on missing/invalid file."""
    try:
        with open(CACHE_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"readings": [], "updated_at": None}
    except json.JSONDecodeError:
        logger.warning("readings_cache.json is corrupted, returning empty cache")
        return {"readings": [], "updated_at": None}


@app.get("/api/readings")
def get_all_readings():
    """Return all cached patient glucose readings."""
    cache = _load_cache()
    return {
        "readings": cache.get("readings", []),
        "updated_at": cache.get("updated_at"),
    }


@app.get("/api/readings/{patient_id}")
def get_patient_reading(patient_id: str):
    """Return the latest glucose reading for a specific patient."""
    cache = _load_cache()
    readings = cache.get("readings", [])
    for reading in readings:
        if reading.get("patient_id") == patient_id:
            return reading
    raise HTTPException(status_code=404, detail=f"Patient '{patient_id}' not found in cache")


@app.get("/api/health")
def get_health():
    """Return API health status and data freshness information."""
    cache = _load_cache()
    updated_at = cache.get("updated_at")
    patient_count = len(cache.get("readings", []))

    age_seconds: float | None = None
    if updated_at:
        try:
            last_update = datetime.fromisoformat(updated_at)
            age_seconds = (datetime.now(timezone.utc) - last_update).total_seconds()
        except ValueError:
            age_seconds = None

    return {
        "status": "ok",
        "patient_count": patient_count,
        "updated_at": updated_at,
        "cache_age_seconds": age_seconds,
    }


@app.get("/api/alerts")
def get_alert_history(patient_id: Optional[str] = None, hours: int = 24):
    """Return alert history for the last *hours* hours.

    Optionally filter by *patient_id*.  Returns an empty list when there are no
    alerts or the database does not exist yet.
    """
    alerts = get_alerts(DB_FILE, patient_id=patient_id, hours=hours)
    return alerts
