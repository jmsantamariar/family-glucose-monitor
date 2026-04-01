"""FastAPI REST API server for external consumption (widgets, dashboards, etc.).

This module provides the **external read-only API** whose routes are distinct
from the authenticated dashboard served by ``src/api.py``:

* ``src/api.py``        — Authenticated internal dashboard (login, setup, patient
                          cache, alert history).  Runs on the dashboard port
                          (default 8080).  All routes require a session cookie.
* ``src/api_server.py`` — Unauthenticated external read-only REST API backed by
                          the ``readings_cache.json`` file written by the polling
                          daemon.  Intended for widgets, Home Assistant, or other
                          local integrations.  Runs on a separate port (default
                          8081, configurable).

Route contracts are intentionally different:

* ``/api/health`` here returns ``patient_count`` / ``updated_at`` /
  ``cache_age_seconds`` (file-cache freshness).
* ``/api/health`` in ``api.py`` returns ``patients_monitored`` / ``timestamp``
  (in-memory cache snapshot).

CORS origins are restricted by default.  Set the ``CORS_ALLOWED_ORIGINS``
environment variable to a comma-separated list of allowed origins when the API
needs to be reached from a browser on a different origin, e.g.::

    CORS_ALLOWED_ORIGINS=http://localhost:3000,https://dashboard.example.com
"""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Query
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

# ---------------------------------------------------------------------------
# CORS — restricted by default to protect health data.
# Override via the CORS_ALLOWED_ORIGINS environment variable.
# ---------------------------------------------------------------------------
_cors_origins_raw = os.environ.get("CORS_ALLOWED_ORIGINS", "")
_cors_origins: list[str] = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Add HTTP security headers to every response."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


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
def get_alert_history(patient_id: Optional[str] = None, hours: int = Query(default=24, ge=1, le=8760)):
    """Return alert history for the last *hours* hours.

    Optionally filter by *patient_id*.  Returns an empty list when there are no
    alerts or the database does not exist yet.
    """
    alerts = get_alerts(DB_FILE, patient_id=patient_id, hours=hours)
    return alerts
