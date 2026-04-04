"""Unit tests for src.connection_tester.test_telegram."""
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.connection_tester import test_telegram as _test_telegram

TEST_TOKEN = "123456:ABC-test-token"
TEST_CHAT = "-100123456789"
TEST_MESSAGE = (
    "✅ Monitor de Glucosa Familiar: prueba de conexión exitosa. "
    "Las alertas de glucosa se enviarán a este chat."
)


def _mock_resp(ok: bool, status_code: int = 200, json_data: dict | None = None):
    resp = MagicMock()
    resp.ok = ok
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    return resp


# ---------------------------------------------------------------------------
# Missing credentials
# ---------------------------------------------------------------------------


def test_missing_token_returns_error():
    result = _test_telegram("", TEST_CHAT)
    assert result["ok"] is False
    assert "obligatorios" in result["message"]


def test_missing_chat_returns_error():
    result = _test_telegram(TEST_TOKEN, "")
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# Successful send
# ---------------------------------------------------------------------------


def test_success_returns_ok_true():
    with patch("src.connection_tester._requests.post") as mock_post:
        mock_post.return_value = _mock_resp(ok=True)
        result = _test_telegram(TEST_TOKEN, TEST_CHAT)
    assert result["ok"] is True
    assert "correctamente" in result["message"].lower()


def test_success_sends_required_message_text():
    """Verifies the real test message text is sent to Telegram."""
    with patch("src.connection_tester._requests.post") as mock_post:
        mock_post.return_value = _mock_resp(ok=True)
        _test_telegram(TEST_TOKEN, TEST_CHAT)

    call_kwargs = mock_post.call_args
    payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
    assert payload["text"] == TEST_MESSAGE
    assert payload["chat_id"] == TEST_CHAT


def test_success_calls_correct_url():
    with patch("src.connection_tester._requests.post") as mock_post:
        mock_post.return_value = _mock_resp(ok=True)
        _test_telegram(TEST_TOKEN, TEST_CHAT)

    url = mock_post.call_args[0][0]
    assert f"/bot{TEST_TOKEN}/sendMessage" in url


# ---------------------------------------------------------------------------
# Telegram API error responses
# ---------------------------------------------------------------------------


def test_invalid_token_401():
    with patch("src.connection_tester._requests.post") as mock_post:
        mock_post.return_value = _mock_resp(ok=False, status_code=401)
        result = _test_telegram(TEST_TOKEN, TEST_CHAT)
    assert result["ok"] is False
    assert "token" in result["message"].lower() or "inválido" in result["message"].lower()


def test_chat_not_found_400():
    with patch("src.connection_tester._requests.post") as mock_post:
        mock_post.return_value = _mock_resp(
            ok=False, status_code=400, json_data={"description": "chat not found"}
        )
        result = _test_telegram(TEST_TOKEN, TEST_CHAT)
    assert result["ok"] is False
    assert "chat" in result["message"].lower()


def test_generic_400_error():
    with patch("src.connection_tester._requests.post") as mock_post:
        mock_post.return_value = _mock_resp(
            ok=False, status_code=400, json_data={"description": "Bad Request: invalid chat_id"}
        )
        result = _test_telegram(TEST_TOKEN, TEST_CHAT)
    assert result["ok"] is False
    assert "400" in result["message"] or "inválido" in result["message"].lower()


def test_other_non_ok_status():
    with patch("src.connection_tester._requests.post") as mock_post:
        mock_post.return_value = _mock_resp(ok=False, status_code=403, json_data={"description": "Forbidden"})
        result = _test_telegram(TEST_TOKEN, TEST_CHAT)
    assert result["ok"] is False
    assert "403" in result["message"]


# ---------------------------------------------------------------------------
# Network / request exceptions
# ---------------------------------------------------------------------------


def test_timeout_returns_error():
    with patch("src.connection_tester._requests.post") as mock_post:
        mock_post.side_effect = requests.exceptions.Timeout()
        result = _test_telegram(TEST_TOKEN, TEST_CHAT)
    assert result["ok"] is False
    assert "timeout" in result["message"].lower()


def test_connection_error_returns_error():
    with patch("src.connection_tester._requests.post") as mock_post:
        mock_post.side_effect = requests.exceptions.ConnectionError()
        result = _test_telegram(TEST_TOKEN, TEST_CHAT)
    assert result["ok"] is False
    assert "red" in result["message"].lower()


def test_generic_request_exception_returns_error():
    with patch("src.connection_tester._requests.post") as mock_post:
        mock_post.side_effect = requests.RequestException("unexpected error")
        result = _test_telegram(TEST_TOKEN, TEST_CHAT)
    assert result["ok"] is False
