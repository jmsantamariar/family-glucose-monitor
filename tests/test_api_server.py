"""Tests for api_server module using FastAPI TestClient."""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import src.api_server as _api_server_module
from src.api_server import app

# Bypass authentication for tests that do not specifically test auth behaviour.
# The module-level client assumes ALLOW_INSECURE_LOCAL_API=True so existing
# tests remain unaffected.  Auth-specific tests reload the module with the
# appropriate env vars set.
_api_server_module.ALLOW_INSECURE_LOCAL_API = True

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
    with patch.object(_api_server_module, "_config", {"api": {"cache_file": str(cache_file)}}):
        response = client.get("/api/readings")
    assert response.status_code == 200
    data = response.json()
    assert "readings" in data
    assert len(data["readings"]) == 2


def test_get_all_readings_includes_updated_at(tmp_path):
    cache_file = tmp_path / "readings_cache.json"
    cache_file.write_text(json.dumps(SAMPLE_CACHE))
    with patch.object(_api_server_module, "_config", {"api": {"cache_file": str(cache_file)}}):
        response = client.get("/api/readings")
    assert response.status_code == 200
    data = response.json()
    assert data["updated_at"] == "2026-01-01T10:05:00+00:00"


def test_get_all_readings_empty_when_no_cache():
    with patch.object(_api_server_module, "_config", {"api": {"cache_file": "/nonexistent/path/readings_cache.json"}}):
        response = client.get("/api/readings")
    assert response.status_code == 200
    data = response.json()
    assert data["readings"] == []
    assert data["updated_at"] is None


def test_get_all_readings_empty_when_cache_corrupted(tmp_path):
    cache_file = tmp_path / "readings_cache.json"
    cache_file.write_text("not valid json{{{")
    with patch.object(_api_server_module, "_config", {"api": {"cache_file": str(cache_file)}}):
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
    with patch.object(_api_server_module, "_config", {"api": {"cache_file": str(cache_file)}}):
        response = client.get("/api/readings/patient-001")
    assert response.status_code == 200
    data = response.json()
    assert data["patient_id"] == "patient-001"
    assert data["value"] == 120


def test_get_patient_reading_second_patient(tmp_path):
    cache_file = tmp_path / "readings_cache.json"
    cache_file.write_text(json.dumps(SAMPLE_CACHE))
    with patch.object(_api_server_module, "_config", {"api": {"cache_file": str(cache_file)}}):
        response = client.get("/api/readings/patient-002")
    assert response.status_code == 200
    data = response.json()
    assert data["patient_id"] == "patient-002"
    assert data["value"] == 200


def test_get_patient_reading_not_found(tmp_path):
    cache_file = tmp_path / "readings_cache.json"
    cache_file.write_text(json.dumps(SAMPLE_CACHE))
    with patch.object(_api_server_module, "_config", {"api": {"cache_file": str(cache_file)}}):
        response = client.get("/api/readings/nonexistent-id")
    assert response.status_code == 404
    assert "nonexistent-id" in response.json()["detail"]


def test_get_patient_reading_no_cache():
    with patch.object(_api_server_module, "_config", {"api": {"cache_file": "/nonexistent/path/readings_cache.json"}}):
        response = client.get("/api/readings/patient-001")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/health
# ---------------------------------------------------------------------------

def test_health_ok_with_cache(tmp_path):
    cache_file = tmp_path / "readings_cache.json"
    cache_file.write_text(json.dumps(SAMPLE_CACHE))
    with patch.object(_api_server_module, "_config", {"api": {"cache_file": str(cache_file)}}):
        response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["patient_count"] == 2
    assert data["updated_at"] == "2026-01-01T10:05:00+00:00"


def test_health_ok_no_cache():
    with patch.object(_api_server_module, "_config", {"api": {"cache_file": "/nonexistent/path/readings_cache.json"}}):
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
    with patch.object(_api_server_module, "_config", {"api": {"cache_file": str(cache_file)}}):
        response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    # Allow some tolerance for test execution time
    assert 85 <= data["cache_age_seconds"] <= 120


def test_health_zero_patients_when_empty_readings(tmp_path):
    cache = _make_cache(readings=[])
    cache_file = tmp_path / "readings_cache.json"
    cache_file.write_text(json.dumps(cache))
    with patch.object(_api_server_module, "_config", {"api": {"cache_file": str(cache_file)}}):
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
    with patch.object(_api_server_module, "_config", {"api": {"cache_file": str(cache_file)}}):
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
    with patch.object(api_server_module, "_config", {"api": {"cache_file": str(cache_file)}}):
        response = test_client.get(
            "/api/readings", headers={"Origin": "http://localhost:3000"}
        )
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"

    # Restore original module state
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    importlib.reload(api_server_module)


# ---------------------------------------------------------------------------
# API key authentication
# ---------------------------------------------------------------------------

def test_no_api_key_no_allow_insecure_blocks_all(tmp_path, monkeypatch):
    """When API_KEY is not set and ALLOW_INSECURE_LOCAL_API is not set, all requests return 401.

    This is the secure-by-default behaviour introduced in Iteration 1.
    """
    import importlib
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("ALLOW_INSECURE_LOCAL_API", raising=False)
    import src.api_server as api_server_module
    importlib.reload(api_server_module)
    cache_file = tmp_path / "readings_cache.json"
    cache_file.write_text(json.dumps(SAMPLE_CACHE))
    test_client = TestClient(api_server_module.app)
    with patch.object(api_server_module, "_config", {"api": {"cache_file": str(cache_file)}}):
        response = test_client.get("/api/readings")
    assert response.status_code == 401
    monkeypatch.delenv("ALLOW_INSECURE_LOCAL_API", raising=False)
    importlib.reload(api_server_module)


def test_allow_insecure_local_api_bypasses_auth(tmp_path, monkeypatch):
    """ALLOW_INSECURE_LOCAL_API=1 without API_KEY allows unauthenticated access (dev only)."""
    import importlib
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.setenv("ALLOW_INSECURE_LOCAL_API", "1")
    import src.api_server as api_server_module
    importlib.reload(api_server_module)
    cache_file = tmp_path / "readings_cache.json"
    cache_file.write_text(json.dumps(SAMPLE_CACHE))
    test_client = TestClient(api_server_module.app)
    with patch.object(api_server_module, "_config", {"api": {"cache_file": str(cache_file)}}):
        response = test_client.get("/api/readings")
    assert response.status_code == 200
    monkeypatch.delenv("ALLOW_INSECURE_LOCAL_API", raising=False)
    importlib.reload(api_server_module)


def test_api_key_set_blocks_unauthenticated(tmp_path, monkeypatch):
    """When API_KEY is set, requests without the key return 401."""
    import importlib
    monkeypatch.setenv("API_KEY", "test-secret-key")
    import src.api_server as api_server_module
    importlib.reload(api_server_module)
    cache_file = tmp_path / "readings_cache.json"
    cache_file.write_text(json.dumps(SAMPLE_CACHE))
    test_client = TestClient(api_server_module.app)
    with patch.object(api_server_module, "_config", {"api": {"cache_file": str(cache_file)}}):
        response = test_client.get("/api/readings")
    assert response.status_code == 401
    monkeypatch.delenv("API_KEY", raising=False)
    importlib.reload(api_server_module)


def test_api_key_set_allows_correct_key(tmp_path, monkeypatch):
    """When API_KEY is set, a correct Authorization: Bearer header grants access."""
    import importlib
    monkeypatch.setenv("API_KEY", "test-secret-key")
    import src.api_server as api_server_module
    importlib.reload(api_server_module)
    cache_file = tmp_path / "readings_cache.json"
    cache_file.write_text(json.dumps(SAMPLE_CACHE))
    test_client = TestClient(api_server_module.app)
    with patch.object(api_server_module, "_config", {"api": {"cache_file": str(cache_file)}}):
        response = test_client.get(
            "/api/readings",
            headers={"Authorization": "Bearer test-secret-key"},
        )
    assert response.status_code == 200
    monkeypatch.delenv("API_KEY", raising=False)
    importlib.reload(api_server_module)


def test_api_key_set_blocks_wrong_key(tmp_path, monkeypatch):
    """When API_KEY is set, a wrong key returns 401."""
    import importlib
    monkeypatch.setenv("API_KEY", "test-secret-key")
    import src.api_server as api_server_module
    importlib.reload(api_server_module)
    cache_file = tmp_path / "readings_cache.json"
    cache_file.write_text(json.dumps(SAMPLE_CACHE))
    test_client = TestClient(api_server_module.app)
    with patch.object(api_server_module, "_config", {"api": {"cache_file": str(cache_file)}}):
        response = test_client.get(
            "/api/readings",
            headers={"Authorization": "Bearer wrong-key"},
        )
    assert response.status_code == 401
    monkeypatch.delenv("API_KEY", raising=False)
    importlib.reload(api_server_module)


def test_alerts_hours_max_is_168(monkeypatch):
    """The /api/alerts endpoint must reject hours > 168."""
    import importlib
    monkeypatch.setenv("ALLOW_INSECURE_LOCAL_API", "1")
    monkeypatch.delenv("API_KEY", raising=False)
    import src.api_server as api_server_module
    importlib.reload(api_server_module)
    test_client = TestClient(api_server_module.app)
    with patch("src.alert_history.get_alerts", return_value=[]):
        response = test_client.get("/api/alerts?hours=200")
    assert response.status_code == 422  # Exceeds le=168 constraint
    monkeypatch.delenv("ALLOW_INSECURE_LOCAL_API", raising=False)
    importlib.reload(api_server_module)


# ---------------------------------------------------------------------------
# _load_config_file
# ---------------------------------------------------------------------------

def test_load_config_file_valid(tmp_path, monkeypatch):
    """_load_config_file returns the parsed dict for a valid config.yaml."""
    import importlib
    import src.api_server as api_server_module
    config_file = tmp_path / "config.yaml"
    config_file.write_text("alert_history_db: /tmp/alerts.db\n")
    monkeypatch.setattr(api_server_module, "PROJECT_ROOT", tmp_path)
    result = api_server_module._load_config_file()
    assert result == {"alert_history_db": "/tmp/alerts.db"}


def test_load_config_file_invalid_not_dict(tmp_path, monkeypatch):
    """_load_config_file returns {} when the YAML does not parse to a dict."""
    import src.api_server as api_server_module
    config_file = tmp_path / "config.yaml"
    config_file.write_text("- item1\n- item2\n")
    monkeypatch.setattr(api_server_module, "PROJECT_ROOT", tmp_path)
    result = api_server_module._load_config_file()
    assert result == {}


# ---------------------------------------------------------------------------
# get_db_path
# ---------------------------------------------------------------------------

def test_get_db_path_from_env(monkeypatch):
    """get_db_path returns the ALERT_HISTORY_DB env var when set."""
    import src.api_server as api_server_module
    monkeypatch.setenv("ALERT_HISTORY_DB", "/custom/path/alerts.db")
    result = api_server_module.get_db_path()
    assert result == "/custom/path/alerts.db"
    monkeypatch.delenv("ALERT_HISTORY_DB", raising=False)


def test_get_db_path_from_config(monkeypatch):
    """get_db_path returns the resolved config path when env var is not set."""
    import src.api_server as api_server_module
    monkeypatch.delenv("ALERT_HISTORY_DB", raising=False)
    with patch.object(api_server_module, "_config", {"alert_history_db": "custom_alerts.db"}):
        result = api_server_module.get_db_path()
    assert result == str(api_server_module.PROJECT_ROOT / "custom_alerts.db")


def test_get_db_path_from_config_absolute(monkeypatch):
    """get_db_path returns an absolute config path unchanged."""
    import src.api_server as api_server_module
    monkeypatch.delenv("ALERT_HISTORY_DB", raising=False)
    with patch.object(api_server_module, "_config", {"alert_history_db": "/abs/alerts.db"}):
        result = api_server_module.get_db_path()
    assert result == "/abs/alerts.db"


def test_get_db_path_default(monkeypatch):
    """get_db_path falls back to PROJECT_ROOT/alert_history.db when nothing is configured."""
    import src.api_server as api_server_module
    monkeypatch.delenv("ALERT_HISTORY_DB", raising=False)
    with patch.object(api_server_module, "_config", {}):
        result = api_server_module.get_db_path()
    assert result == str(api_server_module.PROJECT_ROOT / "alert_history.db")


# ---------------------------------------------------------------------------
# /api/alerts uses get_db_path
# ---------------------------------------------------------------------------

def test_alerts_endpoint_uses_get_db_path(monkeypatch):
    """The /api/alerts endpoint calls get_db_path() instead of a hardcoded constant."""
    import src.api_server as api_server_module
    called_with = []

    def mock_get_alerts(db_path, **kwargs):
        called_with.append(db_path)
        return []

    with patch.object(api_server_module, "get_db_path", return_value="/resolved/alerts.db") as mock_gdb, \
         patch.object(api_server_module, "ALLOW_INSECURE_LOCAL_API", True), \
         patch.object(api_server_module, "API_KEY", None), \
         patch.object(api_server_module, "get_alerts", side_effect=mock_get_alerts):
        test_client = TestClient(api_server_module.app)
        response = test_client.get("/api/alerts")

    assert response.status_code == 200
    mock_gdb.assert_called_once()
    assert called_with == ["/resolved/alerts.db"]
