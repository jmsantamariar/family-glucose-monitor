"""Lightweight REST API to expose latest glucose readings for widgets and external clients."""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_FILE = PROJECT_ROOT / "readings_cache.json"

app = FastAPI(
    title="Family Glucose Monitor API",
    description="REST API to expose glucose readings for widgets (Android, Apple Watch, web dashboards)",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _load_cache() -> dict:
    """Load cached readings from JSON file."""
    try:
        with open(CACHE_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="No readings available yet. Run the monitor first: python -m src.main",
        )
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Cache file is corrupted")


@app.get("/api/readings")
def get_all_readings():
    """Return latest glucose readings for all patients."""
    cache = _load_cache()
    return cache


@app.get("/api/readings/{patient_id}")
def get_patient_reading(patient_id: str):
    """Return the latest reading for a specific patient."""
    cache = _load_cache()
    readings = cache.get("readings", [])
    for reading in readings:
        if reading.get("patient_id") == patient_id:
            return reading
    raise HTTPException(status_code=404, detail=f"Patient {patient_id} not found")


@app.get("/api/health")
def health_check():
    """Return API health status and data freshness."""
    try:
        cache = _load_cache()
        return {
            "status": "ok",
            "last_updated": cache.get("last_updated"),
            "patient_count": len(cache.get("readings", [])),
        }
    except HTTPException:
        return {
            "status": "ok",
            "last_updated": None,
            "patient_count": 0,
            "warning": "No cached readings available yet",
        }
