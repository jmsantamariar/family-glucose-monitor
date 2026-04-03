"""Tests for src.glucose_reader module."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest

from src.glucose_reader import _retry_with_backoff, read_all_patients

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CONFIG = {
    "librelinkup": {
        "email": "user@example.com",
        "password": "secret",
        "region": "EU",
    }
}


def _make_patient(first="John", last="Doe", pid="p1"):
    p = MagicMock()
    p.first_name = first
    p.last_name = last
    p.patient_id = pid
    return p


def _make_latest(value=150, trend_name="Flat", trend_indicator="→", is_high=False, is_low=False):
    latest = MagicMock()
    latest.value = value
    latest.factory_timestamp = datetime.now(timezone.utc)
    latest.trend.name = trend_name
    latest.trend.indicator = trend_indicator
    latest.is_high = is_high
    latest.is_low = is_low
    return latest


# ---------------------------------------------------------------------------
# Successful auth and patient reading collection
# ---------------------------------------------------------------------------

def test_successful_read_returns_reading():
    """Successful auth returns a reading for every patient with data."""
    patient = _make_patient()
    latest = _make_latest(value=130)

    mock_client = MagicMock()
    mock_client.get_patients.return_value = [patient]
    mock_client.latest.return_value = latest

    with patch("src.glucose_reader.PyLibreLinkUp", return_value=mock_client):
        readings = read_all_patients(_CONFIG)

    assert len(readings) == 1
    r = readings[0]
    assert r["patient_id"] == "p1"
    assert r["patient_name"] == "John Doe"
    assert r["value"] == 130
    assert r["trend_arrow"] == "→"
    assert "timestamp" in r


def test_successful_read_multiple_patients():
    """All patients are returned when each has valid data."""
    p1 = _make_patient("Alice", "Smith", "p1")
    p2 = _make_patient("Bob", "Jones", "p2")
    latest1 = _make_latest(value=90)
    latest2 = _make_latest(value=200)

    mock_client = MagicMock()
    mock_client.get_patients.return_value = [p1, p2]
    mock_client.latest.side_effect = [latest1, latest2]

    with patch("src.glucose_reader.PyLibreLinkUp", return_value=mock_client):
        readings = read_all_patients(_CONFIG)

    assert len(readings) == 2
    ids = {r["patient_id"] for r in readings}
    assert ids == {"p1", "p2"}


def test_credentials_read_from_config():
    """Email and password are passed from config to the client constructor."""
    mock_client = MagicMock()
    mock_client.get_patients.return_value = []

    with patch("src.glucose_reader.PyLibreLinkUp", return_value=mock_client) as mock_cls:
        read_all_patients(_CONFIG)

    mock_cls.assert_called_once()
    _, kwargs = mock_cls.call_args
    assert kwargs["email"] == "user@example.com"
    assert kwargs["password"] == "secret"


def test_credentials_read_from_env(monkeypatch):
    """Environment variables override config credentials."""
    monkeypatch.setenv("LIBRELINKUP_EMAIL", "env@example.com")
    monkeypatch.setenv("LIBRELINKUP_PASSWORD", "envpass")

    mock_client = MagicMock()
    mock_client.get_patients.return_value = []

    with patch("src.glucose_reader.PyLibreLinkUp", return_value=mock_client) as mock_cls:
        read_all_patients(_CONFIG)

    _, kwargs = mock_cls.call_args
    assert kwargs["email"] == "env@example.com"
    assert kwargs["password"] == "envpass"


# ---------------------------------------------------------------------------
# Redirect handling
# ---------------------------------------------------------------------------

def test_redirect_is_handled():
    """A RedirectError causes re-authentication with the redirected region."""
    from pylibrelinkup.api_url import APIUrl
    from pylibrelinkup.exceptions import RedirectError

    patient = _make_patient()
    latest = _make_latest()

    first_client = MagicMock()
    first_client.authenticate.side_effect = RedirectError(region=APIUrl.EU)

    second_client = MagicMock()
    second_client.get_patients.return_value = [patient]
    second_client.latest.return_value = latest

    with patch("src.glucose_reader.PyLibreLinkUp", side_effect=[first_client, second_client]):
        readings = read_all_patients(_CONFIG)

    assert len(readings) == 1
    second_client.authenticate.assert_called_once()


def test_redirect_uses_redirected_region():
    """After a RedirectError, the second client is built with the new region URL."""
    from pylibrelinkup.api_url import APIUrl
    from pylibrelinkup.exceptions import RedirectError

    first_client = MagicMock()
    first_client.authenticate.side_effect = RedirectError(region=APIUrl.EU)

    second_client = MagicMock()
    second_client.get_patients.return_value = []

    with patch("src.glucose_reader.PyLibreLinkUp", side_effect=[first_client, second_client]) as mock_cls:
        read_all_patients(_CONFIG)

    assert mock_cls.call_count == 2
    _, kwargs = mock_cls.call_args_list[1]
    assert kwargs["api_url"] == APIUrl.EU


# ---------------------------------------------------------------------------
# Empty patient list
# ---------------------------------------------------------------------------

def test_empty_patient_list_returns_empty():
    """When the account has no patients, an empty list is returned."""
    mock_client = MagicMock()
    mock_client.get_patients.return_value = []

    with patch("src.glucose_reader.PyLibreLinkUp", return_value=mock_client):
        readings = read_all_patients(_CONFIG)

    assert readings == []


def test_patient_with_no_latest_data_is_skipped():
    """A patient whose latest reading is None is skipped without error."""
    patient = _make_patient()

    mock_client = MagicMock()
    mock_client.get_patients.return_value = [patient]
    mock_client.latest.return_value = None

    with patch("src.glucose_reader.PyLibreLinkUp", return_value=mock_client):
        readings = read_all_patients(_CONFIG)

    assert readings == []


# ---------------------------------------------------------------------------
# Per-patient failure does not abort all patients
# ---------------------------------------------------------------------------

def test_per_patient_failure_does_not_abort_others():
    """An exception reading one patient is logged but other patients are still read."""
    p1 = _make_patient("Alice", "Smith", "p1")
    p2 = _make_patient("Bob", "Jones", "p2")
    latest_p2 = _make_latest(value=120)

    mock_client = MagicMock()
    mock_client.get_patients.return_value = [p1, p2]
    # p1 exhausts all retries (max_retries=2 → 3 attempts), p2 succeeds
    mock_client.latest.side_effect = [
        Exception("network error"),
        Exception("network error"),
        Exception("network error"),
        latest_p2,
    ]

    with patch("src.glucose_reader.PyLibreLinkUp", return_value=mock_client), \
         patch("src.glucose_reader.time.sleep"):
        readings = read_all_patients(_CONFIG)

    assert len(readings) == 1
    assert readings[0]["patient_id"] == "p2"


def test_per_patient_failure_first_patient_still_reads_second():
    """Failure on first patient returns data for second patient."""
    p1 = _make_patient("Bad", "Patient", "p1")
    p2 = _make_patient("Good", "Patient", "p2")
    latest_p2 = _make_latest(value=85)

    mock_client = MagicMock()
    mock_client.get_patients.return_value = [p1, p2]
    # p1 exhausts all retries (max_retries=2 → 3 attempts), p2 succeeds
    mock_client.latest.side_effect = [
        RuntimeError("API error"),
        RuntimeError("API error"),
        RuntimeError("API error"),
        latest_p2,
    ]

    with patch("src.glucose_reader.PyLibreLinkUp", return_value=mock_client), \
         patch("src.glucose_reader.time.sleep"):
        readings = read_all_patients(_CONFIG)

    assert readings[0]["patient_name"] == "Good Patient"


# ---------------------------------------------------------------------------
# Top-level failure returns empty list
# ---------------------------------------------------------------------------

def test_auth_failure_returns_empty_list():
    """An authentication exception at the top level returns an empty list."""
    mock_client = MagicMock()
    mock_client.authenticate.side_effect = Exception("auth failed")

    with patch("src.glucose_reader.PyLibreLinkUp", return_value=mock_client), \
         patch("src.glucose_reader.time.sleep"):
        readings = read_all_patients(_CONFIG)

    assert readings == []


def test_get_patients_failure_returns_empty_list():
    """An exception calling get_patients returns an empty list."""
    mock_client = MagicMock()
    mock_client.get_patients.side_effect = Exception("connection refused")

    with patch("src.glucose_reader.PyLibreLinkUp", return_value=mock_client), \
         patch("src.glucose_reader.time.sleep"):
        readings = read_all_patients(_CONFIG)

    assert readings == []


# ---------------------------------------------------------------------------
# Retry / Exponential Backoff
# ---------------------------------------------------------------------------

def test_auth_retries_on_transient_failure():
    """authenticate fails twice then succeeds; readings are returned."""
    patient = _make_patient()
    latest = _make_latest(value=130)

    mock_client = MagicMock()
    mock_client.authenticate.side_effect = [
        Exception("timeout"),
        Exception("timeout"),
        None,  # success on 3rd attempt
    ]
    mock_client.get_patients.return_value = [patient]
    mock_client.latest.return_value = latest

    with patch("src.glucose_reader.PyLibreLinkUp", return_value=mock_client), \
         patch("src.glucose_reader.time.sleep"):
        readings = read_all_patients(_CONFIG)

    assert len(readings) == 1
    assert mock_client.authenticate.call_count == 3


def test_auth_exhausts_retries_returns_empty():
    """authenticate always fails; read_all_patients returns []."""
    mock_client = MagicMock()
    mock_client.authenticate.side_effect = Exception("auth failed")

    with patch("src.glucose_reader.PyLibreLinkUp", return_value=mock_client), \
         patch("src.glucose_reader.time.sleep"):
        readings = read_all_patients(_CONFIG)

    assert readings == []
    assert mock_client.authenticate.call_count == 4  # 4 attempts total (max_retries=3)


def test_get_patients_retries_on_failure():
    """get_patients fails once then succeeds; readings are returned."""
    patient = _make_patient()
    latest = _make_latest(value=110)

    mock_client = MagicMock()
    mock_client.get_patients.side_effect = [Exception("network"), [patient]]
    mock_client.latest.return_value = latest

    with patch("src.glucose_reader.PyLibreLinkUp", return_value=mock_client), \
         patch("src.glucose_reader.time.sleep"):
        readings = read_all_patients(_CONFIG)

    assert len(readings) == 1
    assert mock_client.get_patients.call_count == 2


def test_per_patient_latest_retries():
    """latest fails once for a patient then succeeds; reading is returned."""
    patient = _make_patient()
    latest = _make_latest(value=95)

    mock_client = MagicMock()
    mock_client.get_patients.return_value = [patient]
    mock_client.latest.side_effect = [Exception("timeout"), latest]

    with patch("src.glucose_reader.PyLibreLinkUp", return_value=mock_client), \
         patch("src.glucose_reader.time.sleep"):
        readings = read_all_patients(_CONFIG)

    assert len(readings) == 1
    assert readings[0]["value"] == 95
    assert mock_client.latest.call_count == 2


def test_redirect_error_not_retried():
    """RedirectError is propagated immediately from _retry_with_backoff (no retry)."""
    from pylibrelinkup.api_url import APIUrl
    from pylibrelinkup.exceptions import RedirectError

    mock_func = MagicMock(side_effect=RedirectError(region=APIUrl.EU))

    with patch("src.glucose_reader.time.sleep") as mock_sleep:
        with pytest.raises(RedirectError):
            _retry_with_backoff(
                mock_func,
                max_retries=3,
                base_delay=1.0,
                non_retryable_exceptions=(RedirectError,),
            )

    # Function called exactly once — no retries
    assert mock_func.call_count == 1
    mock_sleep.assert_not_called()


def test_retry_backoff_sleeps():
    """time.sleep is called with exponentially increasing delays between retries."""
    call_count = 0

    def flaky():
        nonlocal call_count
        call_count += 1
        if call_count <= 3:
            raise Exception("fail")
        return "ok"

    with patch("src.glucose_reader.time.sleep") as mock_sleep, \
         patch("src.glucose_reader.random.uniform", return_value=1.0):
        result = _retry_with_backoff(flaky, max_retries=3, base_delay=2.0, max_delay=60.0)

    assert result == "ok"
    assert mock_sleep.call_count == 3
    # Delays should be base_delay * 2^attempt * jitter(1.0): 2, 4, 8
    delays = [c.args[0] for c in mock_sleep.call_args_list]
    assert delays == pytest.approx([2.0, 4.0, 8.0])


# ---------------------------------------------------------------------------
# Default region fallback
# ---------------------------------------------------------------------------

def test_default_region_is_eu():
    """When no region is configured, the client is built with APIUrl.EU."""
    from pylibrelinkup.api_url import APIUrl

    config_no_region = {
        "librelinkup": {
            "email": "user@example.com",
            "password": "secret",
        }
    }

    mock_client = MagicMock()
    mock_client.get_patients.return_value = []

    with patch("src.glucose_reader.PyLibreLinkUp", return_value=mock_client) as mock_cls:
        read_all_patients(config_no_region)

    mock_cls.assert_called_once()
    _, kwargs = mock_cls.call_args
    assert kwargs["api_url"] == APIUrl.EU


def test_build_client_unknown_region_falls_back_to_eu():
    """_build_client with an unrecognised region string uses APIUrl.EU."""
    from pylibrelinkup.api_url import APIUrl
    from src.glucose_reader import _build_client

    mock_client = MagicMock()

    with patch("src.glucose_reader.PyLibreLinkUp", return_value=mock_client) as mock_cls:
        _build_client("user@example.com", "secret", "UNKNOWN_REGION")

    mock_cls.assert_called_once()
    _, kwargs = mock_cls.call_args
    assert kwargs["api_url"] == APIUrl.EU
