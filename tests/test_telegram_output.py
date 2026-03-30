"""Tests for TelegramOutput using mocked requests.post."""
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.outputs.telegram import TelegramOutput, TELEGRAM_API_URL


BOT_TOKEN = "123456:ABC-test-token"
CHAT_ID = "-100123456789"


@pytest.fixture
def output():
    return TelegramOutput(bot_token=BOT_TOKEN, chat_id=CHAT_ID)


def _mock_response(ok: bool, status_code: int = 200, text: str = "OK"):
    resp = MagicMock()
    resp.ok = ok
    resp.status_code = status_code
    resp.text = text
    return resp


# ---------------------------------------------------------------------------
# send_success
# ---------------------------------------------------------------------------

def test_send_alert_success(output):
    with patch("src.outputs.telegram.requests.post") as mock_post:
        mock_post.return_value = _mock_response(ok=True)
        result = output.send_alert("Test message", 55, "low")
    assert result is True
    mock_post.assert_called_once()


# ---------------------------------------------------------------------------
# send_failure (API returns non-OK)
# ---------------------------------------------------------------------------

def test_send_alert_failure(output):
    with patch("src.outputs.telegram.requests.post") as mock_post:
        mock_post.return_value = _mock_response(ok=False, status_code=401, text="Unauthorized")
        result = output.send_alert("Test message", 250, "high")
    assert result is False


# ---------------------------------------------------------------------------
# send_exception (network error)
# ---------------------------------------------------------------------------

def test_send_alert_exception(output):
    with patch("src.outputs.telegram.requests.post") as mock_post:
        mock_post.side_effect = requests.RequestException("Connection refused")
        result = output.send_alert("Test message", 55, "low")
    assert result is False


# ---------------------------------------------------------------------------
# payload_format
# ---------------------------------------------------------------------------

def test_send_alert_payload_format(output):
    with patch("src.outputs.telegram.requests.post") as mock_post:
        mock_post.return_value = _mock_response(ok=True)
        output.send_alert("⚠️ Mamá: glucosa en 55 mg/dL ↓ — BAJA", 55, "low")

    call_kwargs = mock_post.call_args
    url = call_kwargs[0][0] if call_kwargs[0] else call_kwargs.kwargs.get("url", "")
    payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")

    assert f"/bot{BOT_TOKEN}/sendMessage" in url
    assert payload["chat_id"] == CHAT_ID
    assert payload["parse_mode"] == "HTML"
    assert "Mamá" in payload["text"]
    assert "55" in payload["text"]


def test_send_alert_uses_correct_api_url(output):
    expected_url = f"{TELEGRAM_API_URL}/bot{BOT_TOKEN}/sendMessage"
    with patch("src.outputs.telegram.requests.post") as mock_post:
        mock_post.return_value = _mock_response(ok=True)
        output.send_alert("msg", 100, "normal")
    called_url = mock_post.call_args[0][0]
    assert called_url == expected_url
