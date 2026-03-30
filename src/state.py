"""State persistence between cron executions via JSON file. Per-patient keyed by patient_id."""
import json
import os
import tempfile


def load_state(path: str) -> dict:
    """Load state from JSON file. Returns empty dict if file not found or invalid."""
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(path: str, state: dict) -> None:
    """Save state dict as JSON with atomic write."""
    dir_name = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    os.replace(tmp_path, path)


def get_patient_state(state: dict, patient_id: str) -> dict:
    """Get state for a specific patient."""
    return state.get(patient_id, {})


def set_patient_state(state: dict, patient_id: str, patient_state: dict) -> None:
    """Set state for a specific patient."""
    state[patient_id] = patient_state


def clear_patient_state(state: dict, patient_id: str) -> None:
    """Clear state for a specific patient."""
    state.pop(patient_id, None)
