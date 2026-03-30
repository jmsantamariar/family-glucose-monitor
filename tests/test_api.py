"""Tests for FastAPI endpoints in src/api.py."""
import pytest
from fastapi.testclient import TestClient

from src.api import app, _get_color, _readings_cache, _cache_lock


@pytest.fixture(autouse=True)
def clear_cache():
    """Ensure a clean readings cache for each test."""
    with _cache_lock:
        _readings_cache.clear()
    yield
    with _cache_lock:
        _readings_cache.clear()


@pytest.fixture
def client():
    return TestClient(app)


# ── /api/health ──────────────────────────────────────────────────────────────

class TestHealthEndpoint:
    def test_returns_200(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_status_is_ok(self, client):
        resp = client.get("/api/health")
        assert resp.json()["status"] == "ok"

    def test_has_timestamp(self, client):
        resp = client.get("/api/health")
        assert "timestamp" in resp.json()

    def test_patients_monitored_zero_when_empty(self, client):
        resp = client.get("/api/health")
        assert resp.json()["patients_monitored"] == 0

    def test_patients_monitored_counts_cache(self, client):
        with _cache_lock:
            _readings_cache["p1"] = {"patient_id": "p1"}
            _readings_cache["p2"] = {"patient_id": "p2"}
        resp = client.get("/api/health")
        assert resp.json()["patients_monitored"] == 2


# ── /api/patients ────────────────────────────────────────────────────────────

class TestPatientsListEndpoint:
    def test_returns_200(self, client):
        resp = client.get("/api/patients")
        assert resp.status_code == 200

    def test_empty_cache_returns_empty_list(self, client):
        resp = client.get("/api/patients")
        data = resp.json()
        assert data["patients"] == []
        assert data["count"] == 0

    def test_returns_all_patients(self, client):
        with _cache_lock:
            _readings_cache["abc"] = {"patient_id": "abc", "patient_name": "Ana"}
            _readings_cache["xyz"] = {"patient_id": "xyz", "patient_name": "Juan"}
        resp = client.get("/api/patients")
        data = resp.json()
        assert data["count"] == 2
        ids = {p["patient_id"] for p in data["patients"]}
        assert ids == {"abc", "xyz"}


# ── /api/patients/{patient_id} ───────────────────────────────────────────────

class TestPatientDetailEndpoint:
    def test_404_for_unknown_patient(self, client):
        resp = client.get("/api/patients/nonexistent")
        assert resp.status_code == 404

    def test_returns_patient_data(self, client):
        with _cache_lock:
            _readings_cache["p42"] = {
                "patient_id": "p42",
                "patient_name": "María",
                "glucose_value": 120,
                "color": "green",
            }
        resp = client.get("/api/patients/p42")
        assert resp.status_code == 200
        data = resp.json()
        assert data["patient_id"] == "p42"
        assert data["patient_name"] == "María"

    def test_404_detail_message(self, client):
        resp = client.get("/api/patients/no-such-id")
        assert "not found" in resp.json()["detail"].lower()


# ── / (dashboard HTML) ───────────────────────────────────────────────────────

class TestDashboardEndpoint:
    def test_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_content_type_is_html(self, client):
        resp = client.get("/")
        assert "text/html" in resp.headers["content-type"]

    def test_html_contains_title(self, client):
        resp = client.get("/")
        assert "Monitor de Glucosa Familiar" in resp.text

    def test_html_contains_disclaimer(self, client):
        resp = client.get("/")
        assert "dispositivo médico" in resp.text

    def test_html_contains_fetch_script(self, client):
        resp = client.get("/")
        assert "fetchPatients" in resp.text


# ── _get_color helper ────────────────────────────────────────────────────────

class TestGetColor:
    def test_low_level_returns_red(self):
        assert _get_color("low", "normal") == "red"

    def test_high_level_returns_red(self):
        assert _get_color("high", "normal") == "red"

    def test_falling_fast_trend_returns_red(self):
        assert _get_color("normal", "falling_fast") == "red"

    def test_falling_trend_returns_yellow(self):
        assert _get_color("normal", "falling") == "yellow"

    def test_rising_fast_trend_returns_yellow(self):
        assert _get_color("normal", "rising_fast") == "yellow"

    def test_normal_level_and_trend_returns_green(self):
        assert _get_color("normal", "normal") == "green"

    def test_normal_level_stable_trend_returns_green(self):
        assert _get_color("normal", "stable") == "green"

    def test_normal_level_rising_trend_returns_green(self):
        # "rising" alone (not "rising_fast") → green (approaching but not urgent)
        assert _get_color("normal", "rising") == "green"
