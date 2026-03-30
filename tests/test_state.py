"""Tests for state module."""
import json
import os
import pytest
import tempfile
from src.state import load_state, save_state, get_patient_state, set_patient_state, clear_patient_state


# --- load_state() ---

def test_load_state_file_not_found():
    result = load_state("/tmp/nonexistent_state_file_xyz.json")
    assert result == {}

def test_load_state_invalid_json(tmp_path):
    f = tmp_path / "state.json"
    f.write_text("not valid json")
    assert load_state(str(f)) == {}

def test_load_state_empty_file(tmp_path):
    f = tmp_path / "state.json"
    f.write_text("")
    assert load_state(str(f)) == {}

def test_load_state_valid_data(tmp_path):
    data = {"patient1": {"last_alert_level": "low"}}
    f = tmp_path / "state.json"
    f.write_text(json.dumps(data))
    result = load_state(str(f))
    assert result == data


# --- save_state() ---

def test_save_state_creates_file(tmp_path):
    state_path = str(tmp_path / "state.json")
    save_state(state_path, {"key": "value"})
    assert os.path.exists(state_path)

def test_save_state_content_matches(tmp_path):
    state_path = str(tmp_path / "state.json")
    data = {"patient1": {"last_alert_level": "high", "last_glucose_value": 200}}
    save_state(state_path, data)
    with open(state_path) as f:
        result = json.load(f)
    assert result == data

def test_save_state_atomic_no_tmp_files_remain(tmp_path):
    state_path = str(tmp_path / "state.json")
    save_state(state_path, {"x": 1})
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert len(tmp_files) == 0

def test_save_and_load_roundtrip(tmp_path):
    state_path = str(tmp_path / "state.json")
    original = {"p1": {"last_alert_level": "low"}, "p2": {"last_alert_level": "high"}}
    save_state(state_path, original)
    loaded = load_state(state_path)
    assert loaded == original


# --- get_patient_state() ---

def test_get_patient_state_existing():
    state = {"p1": {"last_alert_level": "low"}}
    result = get_patient_state(state, "p1")
    assert result == {"last_alert_level": "low"}

def test_get_patient_state_missing():
    state = {}
    result = get_patient_state(state, "p99")
    assert result == {}

def test_get_patient_state_does_not_modify_state():
    state = {}
    get_patient_state(state, "p1")
    assert state == {}


# --- set_patient_state() ---

def test_set_patient_state_adds_entry():
    state = {}
    set_patient_state(state, "p1", {"last_alert_level": "high"})
    assert state["p1"] == {"last_alert_level": "high"}

def test_set_patient_state_overwrites_existing():
    state = {"p1": {"last_alert_level": "low"}}
    set_patient_state(state, "p1", {"last_alert_level": "high"})
    assert state["p1"]["last_alert_level"] == "high"

def test_set_multiple_patients():
    state = {}
    set_patient_state(state, "p1", {"v": 1})
    set_patient_state(state, "p2", {"v": 2})
    assert len(state) == 2
    assert state["p1"]["v"] == 1
    assert state["p2"]["v"] == 2


# --- clear_patient_state() ---

def test_clear_patient_state_removes_entry():
    state = {"p1": {"last_alert_level": "low"}}
    clear_patient_state(state, "p1")
    assert "p1" not in state

def test_clear_patient_state_nonexistent_no_error():
    state = {}
    clear_patient_state(state, "p99")  # should not raise
    assert state == {}

def test_clear_one_of_many_patients():
    state = {"p1": {"v": 1}, "p2": {"v": 2}}
    clear_patient_state(state, "p1")
    assert "p1" not in state
    assert "p2" in state
