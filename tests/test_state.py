"""Tests for state persistence module."""
import json
import os
import tempfile

import pytest

from src.state import (
    clear_patient_state,
    get_patient_state,
    load_state,
    save_state,
    set_patient_state,
)


# ---------------------------------------------------------------------------
# load_state
# ---------------------------------------------------------------------------

def test_load_state_missing_file():
    result = load_state("/tmp/nonexistent_state_file_xyz.json")
    assert result == {}


def test_load_state_invalid_json(tmp_path):
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("not valid json {{{")
    assert load_state(str(bad_file)) == {}


def test_load_state_empty_dict(tmp_path):
    f = tmp_path / "state.json"
    f.write_text("{}")
    assert load_state(str(f)) == {}


# ---------------------------------------------------------------------------
# save_state + load_state roundtrip
# ---------------------------------------------------------------------------

def test_save_and_load_roundtrip(tmp_path):
    path = str(tmp_path / "state.json")
    state = {"patient-1": {"last_alert_level": "high", "last_alert_time": "2026-01-01T00:00:00+00:00"}}
    save_state(path, state)
    loaded = load_state(path)
    assert loaded == state


def test_save_state_atomic_no_tmp_left(tmp_path):
    path = str(tmp_path / "state.json")
    save_state(path, {"x": 1})
    tmp_files = [f for f in os.listdir(tmp_path) if f.endswith(".tmp")]
    assert tmp_files == []


def test_save_state_overwrites_existing(tmp_path):
    path = str(tmp_path / "state.json")
    save_state(path, {"a": 1})
    save_state(path, {"b": 2})
    assert load_state(path) == {"b": 2}


# ---------------------------------------------------------------------------
# get_patient_state
# ---------------------------------------------------------------------------

def test_get_patient_state_empty():
    state = {}
    result = get_patient_state(state, "patient-99")
    assert result == {}


def test_get_patient_state_exists():
    ps = {"last_alert_level": "low"}
    state = {"patient-1": ps}
    assert get_patient_state(state, "patient-1") == ps


# ---------------------------------------------------------------------------
# set_patient_state
# ---------------------------------------------------------------------------

def test_set_patient_state():
    state = {}
    ps = {"last_alert_level": "high"}
    updated = set_patient_state(state, "patient-2", ps)
    assert updated["patient-2"] == ps


def test_set_patient_state_updates_existing():
    state = {"patient-1": {"last_alert_level": "low"}}
    set_patient_state(state, "patient-1", {"last_alert_level": "high"})
    assert state["patient-1"]["last_alert_level"] == "high"


# ---------------------------------------------------------------------------
# clear_patient_state
# ---------------------------------------------------------------------------

def test_clear_patient_state():
    state = {"patient-1": {"last_alert_level": "low", "last_alert_time": "2026-01-01T00:00:00+00:00"}}
    clear_patient_state(state, "patient-1")
    assert "patient-1" not in state


def test_clear_patient_state_nonexistent():
    state = {}
    clear_patient_state(state, "patient-99")
    assert "patient-99" not in state


# ---------------------------------------------------------------------------
# multiple patients
# ---------------------------------------------------------------------------

def test_multiple_patients_independent(tmp_path):
    path = str(tmp_path / "state.json")
    state = {}
    set_patient_state(state, "p1", {"last_alert_level": "low"})
    set_patient_state(state, "p2", {"last_alert_level": "high"})
    set_patient_state(state, "p3", {"last_alert_level": "normal"})
    save_state(path, state)
    loaded = load_state(path)
    assert loaded["p1"]["last_alert_level"] == "low"
    assert loaded["p2"]["last_alert_level"] == "high"
    assert loaded["p3"]["last_alert_level"] == "normal"
    clear_patient_state(loaded, "p1")
    assert "p1" not in loaded
    assert loaded["p2"]["last_alert_level"] == "high"
