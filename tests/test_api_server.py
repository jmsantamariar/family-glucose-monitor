"""Tests for api_server module using FastAPI TestClient."""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.api_server import CACHE_FILE, app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_READINGS = [
    {
        "patient_id": "patient-001",
        "patient_name": "Juan García",
        "value": 120,
        "timestamp": "2026-01-01T10:00:00+00:00",
        "trend_name": "Flat",
        "trend_arrow": "→",
        "is_high": False,
        "is_low": False,
    },
    {
        "patient_id": "patient-002",
        "patient_name": "María García",
        "value": 200,
        "timestamp": "2026-01-01T10:01:00+00:00",
        "trend_name": "SingleUp",
        "trend_arrow": "↑",
        "is_high": True,
        "is_low": False,
    },
]

SAMPLE_CACHE = {
    "readings": SAMPLE_READINGS,
    "updated_at": "2026-01-01T10:05:00+00:00",
}


def _make_cache(readings=None, updated_at=None):
    return {
        "readings": readings if readings is not None else SAMPLE_READINGS,
        "updated_at": updated_at or "2026-01-01T10:05:00+00:00",
    }


# ---------------------------------------------------------------------------
# GET /api/readings
# ---------------------------------------------------------------------------

def test_get_all_readings_returns_list(tmp_path):
    cache_file = tmp_path / "readings_cache.json"
    cache_file.write_text(json.dumps(SAMPLE_CACHE))
    with patch("src.api_server.CACHE_FILE", cache_file):
        response = client.get("/api/readings")
    assert response.status_code == 200
    data = response.json()
    assert "readings" in data
    assert len(data["readings"]) == 2


def test_get_all_readings_includes_updated_at(tmp_path):
    cache_file = tmp_path / "readings_cache.json"
    cache_file.write_text(json.dumps(SAMPLE_CACHE))
    with patch("src.api_server.CACHE_FILE", cache_file):
        response = client.get("/api/readings")
    assert response.status_code == 200
    data = response.json()
    assert data["updated_at"] == "2026-01-01T10:05:00+00:00"


def test_get_all_readings_empty_when_no_cache():
    with patch("src.api_server.CACHE_FILE", "/nonexistent/path/readings_cache.json"):
        response = client.get("/api/readings")
    assert response.status_code == 200
    data = response.json()
    assert data["readings"] == []
    assert data["updated_at"] is None


def test_get_all_readings_empty_when_cache_corrupted(tmp_path):
    cache_file = tmp_path / "readings_cache.json"
    cache_file.write_text("not valid json{{{")
    with patch("src.api_server.CACHE_FILE", cache_file):
        response = client.get("/api/readings")
    assert response.status_code == 200
    data = response.json()
    assert data["readings"] == []


# ---------------------------------------------------------------------------
# GET /api/readings/{patient_id}
# ---------------------------------------------------------------------------

def test_get_patient_reading_found(tmp_path):
    cache_file = tmp_path / "readings_cache.json"
    cache_file.write_text(json.dumps(SAMPLE_CACHE))
    with patch("src.api_server.CACHE_FILE", cache_file):
        response = client.get("/api/readings/patient-001")
    assert response.status_code == 200
    data = response.json()
    assert data["patient_id"] == "patient-001"
    assert data["value"] == 120


def test_get_patient_reading_second_patient(tmp_path):
    cache_file = tmp_path / "readings_cache.json"
    cache_file.write_text(json.dumps(SAMPLE_CACHE))
    with patch("src.api_server.CACHE_FILE", cache_file):
        response = client.get("/api/readings/patient-002")
    assert response.status_code == 200
    data = response.json()
    assert data["patient_id"] == "patient-002"
    assert data["value"] == 200


def test_get_patient_reading_not_found(tmp_path):
    cache_file = tmp_path / "readings_cache.json"
    cache_file.write_text(json.dumps(SAMPLE_CACHE))
    with patch("src.api_server.CACHE_FILE", cache_file):
        response = client.get("/api/readings/nonexistent-id")
    assert response.status_code == 404
    assert "nonexistent-id" in response.json()["detail"]


def test_get_patient_reading_no_cache():
    with patch("src.api_server.CACHE_FILE", "/nonexistent/path/readings_cache.json"):
        response = client.get("/api/readings/patient-001")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/health
# ---------------------------------------------------------------------------

def test_health_ok_with_cache(tmp_path):
    cache_file = tmp_path / "readings_cache.json"
    cache_file.write_text(json.dumps(SAMPLE_CACHE))
    with patch("src.api_server.CACHE_FILE", cache_file):
        response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["patient_count"] == 2
    assert data["updated_at"] == "2026-01-01T10:05:00+00:00"


def test_health_ok_no_cache():
    with patch("src.api_server.CACHE_FILE", "/nonexistent/path/readings_cache.json"):
        response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["patient_count"] == 0
    assert data["updated_at"] is None
    assert data["cache_age_seconds"] is None


def test_health_cache_age_seconds(tmp_path):
    updated_at = datetime.now(timezone.utc) - timedelta(seconds=90)
    cache = _make_cache(updated_at=updated_at.isoformat())
    cache_file = tmp_path / "readings_cache.json"
    cache_file.write_text(json.dumps(cache))
    with patch("src.api_server.CACHE_FILE", cache_file):
        response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    # Allow some tolerance for test execution time
    assert 85 <= data["cache_age_seconds"] <= 120


def test_health_zero_patients_when_empty_readings(tmp_path):
    cache = _make_cache(readings=[])
    cache_file = tmp_path / "readings_cache.json"
    cache_file.write_text(json.dumps(cache))
    with patch("src.api_server.CACHE_FILE", cache_file):
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["patient_count"] == 0


# ---------------------------------------------------------------------------
# CORS headers
# ---------------------------------------------------------------------------

def test_cors_no_wildcard_by_default(tmp_path):
    """By default, CORS wildcard must not be set — origins are empty."""
    cache_file = tmp_path / "readings_cache.json"
    cache_file.write_text(json.dumps(SAMPLE_CACHE))
    with patch("src.api_server.CACHE_FILE", cache_file):
        response = client.get("/api/readings", headers={"Origin": "http://localhost:3000"})
    # No wildcard origin should be in the response by default
    assert response.headers.get("access-control-allow-origin") != "*"


def test_cors_allowed_origin_via_env(tmp_path, monkeypatch):
    """When CORS_ALLOWED_ORIGINS is set, the specified origin is reflected."""
    import importlib

    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000")
    # Reimport the module so CORS middleware is rebuilt with the new env value
    import src.api_server as api_server_module
    importlib.reload(api_server_module)

    cache_file = tmp_path / "readings_cache.json"
    cache_file.write_text(json.dumps(SAMPLE_CACHE))
    test_client = TestClient(api_server_module.app)
    with patch.object(api_server_module, "CACHE_FILE", cache_file):
        response = test_client.get(
            "/api/readings", headers={"Origin": "http://localhost:3000"}
        )
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"

    # Restore original module state
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    importlib.reload(api_server_module)
