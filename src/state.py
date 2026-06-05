"""State persistence between executions via JSON file, keyed by patient ID."""
import json
import os
import tempfile
from contextlib import contextmanager

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None


@contextmanager
def state_lock(path: str):
    """Advisory file lock serialising state.json writers.

    In ``full`` mode the polling thread (run_once) and the dashboard's mute
    endpoints write the same state file from different threads/processes
    with a load→mutate→save pattern; this lock makes each writer's sequence
    atomic. Best-effort no-op on platforms without ``fcntl`` (Windows).
    """
    lock_file = None
    try:
        if fcntl is not None:
            lock_file = open(path + ".lock", "w")
            fcntl.flock(lock_file, fcntl.LOCK_EX)
        yield
    finally:
        if lock_file is not None:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_UN)
            except OSError:
                pass
            lock_file.close()


def merge_silence_mutes(state: dict, disk_state: dict) -> dict:
    """Graft silence mutes from *disk_state* into *state* (mutes win).

    The monitor holds its in-memory copy of the state for a whole polling
    cycle; a caregiver mute saved by the dashboard meanwhile would be
    clobbered on save. Before persisting, any ``silence.muted_until`` found
    on disk and absent in the in-memory copy is preserved.
    """
    for pid, patient_state in disk_state.items():
        if not isinstance(patient_state, dict):
            continue
        muted_until = (patient_state.get("silence") or {}).get("muted_until")
        if not muted_until:
            continue
        target = state.setdefault(pid, {})
        silence = target.setdefault("silence", {})
        silence.setdefault("muted_until", muted_until)
    return state


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
