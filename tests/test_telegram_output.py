"""Tests for TelegramOutput send_alert."""
import pytest
from unittest.mock import MagicMock, patch
from src.outputs.telegram import TelegramOutput


def make_output():
    return TelegramOutput(bot_token="test-token", chat_id="12345")


# --- send_alert success ---

def test_send_alert_success():
    output = make_output()
    mock_resp = MagicMock()
    mock_resp.ok = True
    with patch("src.outputs.telegram.requests.post", return_value=mock_resp) as mock_post:
        result = output.send_alert("Test message", 65, "low")
    assert result is True
    mock_post.assert_called_once()


def test_send_alert_uses_correct_url():
    output = make_output()
    mock_resp = MagicMock()
    mock_resp.ok = True
    with patch("src.outputs.telegram.requests.post", return_value=mock_resp) as mock_post:
        output.send_alert("msg", 65, "low")
    call_args = mock_post.call_args
    assert "bottest-token/sendMessage" in call_args[0][0]


def test_send_alert_sends_correct_payload():
    output = make_output()
    mock_resp = MagicMock()
    mock_resp.ok = True
    with patch("src.outputs.telegram.requests.post", return_value=mock_resp) as mock_post:
        output.send_alert("My alert text", 200, "high")
    payload = mock_post.call_args[1]["json"]
    assert payload["chat_id"] == "12345"
    assert payload["text"] == "My alert text"
    assert payload["parse_mode"] == "HTML"


# --- send_alert API errors ---

def test_send_alert_api_error_returns_false():
    output = make_output()
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 401
    mock_resp.text = "Unauthorized"
    with patch("src.outputs.telegram.requests.post", return_value=mock_resp):
        result = output.send_alert("msg", 65, "low")
    assert result is False


def test_send_alert_500_error_returns_false():
    output = make_output()
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 500
    mock_resp.text = "Internal Server Error"
    with patch("src.outputs.telegram.requests.post", return_value=mock_resp):
        result = output.send_alert("msg", 65, "low")
    assert result is False


# --- send_alert network failures ---

def test_send_alert_network_exception_returns_false():
    import requests as req
    output = make_output()
    with patch("src.outputs.telegram.requests.post", side_effect=req.exceptions.ConnectionError("timeout")):
        result = output.send_alert("msg", 65, "low")
    assert result is False


def test_send_alert_timeout_returns_false():
    import requests as req
    output = make_output()
    with patch("src.outputs.telegram.requests.post", side_effect=req.exceptions.Timeout("timed out")):
        result = output.send_alert("msg", 65, "low")
    assert result is False


# --- constructor ---

def test_output_stores_bot_token_and_chat_id():
    output = TelegramOutput(bot_token="abc123", chat_id="chat999")
    assert output.bot_token == "abc123"
    assert output.chat_id == "chat999"
