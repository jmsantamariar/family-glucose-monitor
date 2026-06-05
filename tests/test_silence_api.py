"""Tests for sensor-silence info in /api/patients and the mute endpoints."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import src.api as api_module
from src.api import app

_MINIMAL_CONFIG = {
    "api": {},
    "alerts": {
        "low_threshold": 70,
        "high_threshold": 180,
        "trend": {"enabled": False},
    },
}


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    monkeypatch.setattr(api_module, "_ALLOW_AUTH_DISABLED", True)
    with api_module._cache_lock:
        api_module._readings_cache.clear()
    api_module._last_mtime = 0.0
    yield
    with api_module._cache_lock:
        api_module._readings_cache.clear()
    api_module._last_mtime = 0.0


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Temp cache (one silent + one fresh patient) + temp state file."""
    now = datetime.now(timezone.utc)
    cache_file = tmp_path / "readings_cache.json"
    cache_file.write_text(json.dumps({
        "readings": [
            {
                "patient_id": "silent-1", "patient_name": "Leticia",
                "value": 110, "trend_arrow": "→",
                "timestamp": (now - timedelta(hours=26)).isoformat(),
            },
            {
                "patient_id": "fresh-1", "patient_name": "Mario",
                "value": 98, "trend_arrow": "→",
                "timestamp": (now - timedelta(minutes=4)).isoformat(),
            },
        ],
        "updated_at": now.isoformat(),
    }))
    state_file = tmp_path / "state.json"
    config = dict(_MINIMAL_CONFIG)
    config["api"] = {"cache_file": str(cache_file)}
    config["state_file"] = str(state_file)
    monkeypatch.setattr(api_module, "_config", config)
    monkeypatch.setattr(api_module, "_reading_history", type(
        "Stub", (), {"init_db": staticmethod(lambda *a, **k: None),
                     "log_reading": staticmethod(lambda *a, **k: None)})())
    return {"client": TestClient(app), "state_file": state_file, "tmp": tmp_path}


# ── silence info attached to patient payloads ────────────────────────────────


def test_patients_include_silence_info(env):
    resp = env["client"].get("/api/patients")
    assert resp.status_code == 200
    by_id = {p["patient_id"]: p for p in resp.json()["patients"]}

    silent = by_id["silent-1"]["silence"]
    assert silent["enabled"] is True
    assert silent["minutes"] >= 26 * 60 - 1
    assert silent["check_after_minutes"] == 60
    assert silent["ask_after_minutes"] == 180
    assert silent["muted_until"] is None

    fresh = by_id["fresh-1"]["silence"]
    assert fresh["minutes"] < 60


def test_single_patient_includes_silence(env):
    resp = env["client"].get("/api/patients/silent-1")
    assert resp.status_code == 200
    assert resp.json()["silence"]["minutes"] >= 26 * 60 - 1


def test_silence_reflects_state_stage_and_mute(env):
    from src.state import save_state
    save_state(str(env["state_file"]), {
        "silent-1": {"silence": {"stage": "stage2", "muted_until": "recovery"}},
    })
    resp = env["client"].get("/api/patients/silent-1")
    sil = resp.json()["silence"]
    assert sil["stage"] == "stage2"
    assert sil["muted_until"] == "recovery"


# ── mute / unmute endpoints ──────────────────────────────────────────────────


def test_mute_24h_writes_state(env):
    resp = env["client"].post(
        "/api/patients/silent-1/silence/mute", json={"duration": "24h"}
    )
    assert resp.status_code == 200
    muted_until = resp.json()["muted_until"]
    parsed = datetime.fromisoformat(muted_until)
    assert parsed > datetime.now(timezone.utc) + timedelta(hours=23)

    from src.state import load_state
    state = load_state(str(env["state_file"]))
    assert state["silent-1"]["silence"]["muted_until"] == muted_until


def test_mute_recovery_literal(env):
    resp = env["client"].post(
        "/api/patients/silent-1/silence/mute", json={"duration": "recovery"}
    )
    assert resp.status_code == 200
    assert resp.json()["muted_until"] == "recovery"


def test_mute_invalid_duration_422(env):
    resp = env["client"].post(
        "/api/patients/silent-1/silence/mute", json={"duration": "forever"}
    )
    assert resp.status_code == 422


def test_mute_unknown_patient_404(env):
    resp = env["client"].post(
        "/api/patients/nope/silence/mute", json={"duration": "24h"}
    )
    assert resp.status_code == 404


def test_mute_preserves_existing_patient_state(env):
    from src.state import load_state, save_state
    save_state(str(env["state_file"]), {
        "silent-1": {"last_alert_level": "low", "last_alert_time": "2026-06-01T00:00:00+00:00"},
    })
    env["client"].post("/api/patients/silent-1/silence/mute", json={"duration": "7d"})
    state = load_state(str(env["state_file"]))
    assert state["silent-1"]["last_alert_level"] == "low"  # untouched
    assert "muted_until" in state["silent-1"]["silence"]


def test_unmute_clears_mute_keeps_stage(env):
    from src.state import load_state, save_state
    save_state(str(env["state_file"]), {
        "silent-1": {"silence": {"stage": "stage2", "muted_until": "recovery"}},
    })
    resp = env["client"].post("/api/patients/silent-1/silence/unmute")
    assert resp.status_code == 200
    state = load_state(str(env["state_file"]))
    assert state["silent-1"]["silence"]["stage"] == "stage2"
    assert "muted_until" not in state["silent-1"]["silence"]


def test_unmute_when_nothing_muted_is_noop(env):
    resp = env["client"].post("/api/patients/silent-1/silence/unmute")
    assert resp.status_code == 200
    from src.state import load_state
    assert load_state(str(env["state_file"])) == {}
