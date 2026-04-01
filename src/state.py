"""State persistence between executions via JSON file, keyed by patient ID."""
import json
import os
import tempfile


def load_state(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(path: str, state: dict) -> None:
    dir_name = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    os.replace(tmp_path, path)


def get_patient_state(state: dict, patient_id: str) -> dict:
    return state.get(patient_id, {})


def set_patient_state(state: dict, patient_id: str, patient_state: dict) -> dict:
    state[patient_id] = patient_state
    return state


def clear_patient_state(state: dict, patient_id: str) -> dict:
    state.pop(patient_id, None)
    return state
