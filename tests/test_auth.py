"""Tests for src/auth.py and authentication-related API endpoints."""
import time
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from fastapi.testclient import TestClient

from src.api import app
from src.auth import SESSION_TTL, SessionManager, is_configured, session_manager, verify_credentials


# ── SessionManager ────────────────────────────────────────────────────────────


class TestSessionManager:
    def setup_method(self):
        session_manager.clear_all()

    def teardown_method(self):
        session_manager.clear_all()

    def test_create_session_returns_token(self):
        token = session_manager.create_session()
        assert isinstance(token, str)
        assert len(token) == 64  # 32 bytes hex = 64 chars

    def test_new_token_is_valid(self):
        token = session_manager.create_session()
        assert session_manager.is_valid(token)

    def test_none_token_is_invalid(self):
        assert not session_manager.is_valid(None)

    def test_unknown_token_is_invalid(self):
        assert not session_manager.is_valid("nonexistenttoken")

    def test_invalidate_removes_session(self):
        token = session_manager.create_session()
        session_manager.invalidate(token)
        assert not session_manager.is_valid(token)

    def test_invalidate_unknown_token_does_not_raise(self):
        session_manager.invalidate("ghost_token")  # Should not raise

    def test_expired_token_is_invalid(self):
        mgr = SessionManager()
        token = mgr.create_session()
        # Simulate expired session by patching time.time to return a future time
        with patch("src.auth.time") as mock_time:
            mock_time.time.return_value = time.time() + SESSION_TTL + 1
            assert not mgr.is_valid(token)

    def test_clear_all_removes_all_sessions(self):
        t1 = session_manager.create_session()
        t2 = session_manager.create_session()
        session_manager.clear_all()
        assert not session_manager.is_valid(t1)
        assert not session_manager.is_valid(t2)


# ── is_configured ─────────────────────────────────────────────────────────────


class TestIsConfigured:
    def test_true_when_config_exists(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("librelinkup:\n  email: a@b.com\n")
        with patch("src.auth._CONFIG_PATH", cfg):
            assert is_configured()

    def test_false_when_config_missing(self, tmp_path):
        missing = tmp_path / "config.yaml"
        with patch("src.auth._CONFIG_PATH", missing):
            assert not is_configured()


# ── verify_credentials ────────────────────────────────────────────────────────


class TestVerifyCredentials:
    def _make_config(self, tmp_path, email: str, password: str) -> Path:
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            yaml.dump({"librelinkup": {"email": email, "password": password}})
        )
        return cfg

    def test_correct_credentials(self, tmp_path):
        cfg = self._make_config(tmp_path, "user@example.com", "secret")
        with patch("src.auth._CONFIG_PATH", cfg):
            assert verify_credentials("user@example.com", "secret")

    def test_wrong_password(self, tmp_path):
        cfg = self._make_config(tmp_path, "user@example.com", "secret")
        with patch("src.auth._CONFIG_PATH", cfg):
            assert not verify_credentials("user@example.com", "wrong")

    def test_wrong_email(self, tmp_path):
        cfg = self._make_config(tmp_path, "user@example.com", "secret")
        with patch("src.auth._CONFIG_PATH", cfg):
            assert not verify_credentials("other@example.com", "secret")

    def test_missing_config_returns_false(self, tmp_path):
        missing = tmp_path / "config.yaml"
        with patch("src.auth._CONFIG_PATH", missing):
            assert not verify_credentials("user@example.com", "secret")

    def test_empty_credentials_returns_false(self, tmp_path):
        cfg = self._make_config(tmp_path, "user@example.com", "secret")
        with patch("src.auth._CONFIG_PATH", cfg):
            assert not verify_credentials("", "")


# ── /api/setup/status ─────────────────────────────────────────────────────────


class TestSetupStatus:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_returns_false_when_not_configured(self, client, tmp_path):
        missing = tmp_path / "config.yaml"
        with patch("src.api.is_configured", return_value=False):
            resp = client.get("/api/setup/status")
        assert resp.status_code == 200
        assert resp.json() == {"configured": False}

    def test_returns_true_when_configured(self, client):
        with patch("src.api.is_configured", return_value=True):
            resp = client.get("/api/setup/status")
        assert resp.status_code == 200
        assert resp.json() == {"configured": True}


# ── /api/login ────────────────────────────────────────────────────────────────


class TestLoginEndpoint:
    @pytest.fixture
    def client(self):
        session_manager.clear_all()
        yield TestClient(app)
        session_manager.clear_all()

    def test_valid_credentials_returns_200(self, client, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            yaml.dump({"librelinkup": {"email": "a@b.com", "password": "pass"}})
        )
        with patch("src.auth._CONFIG_PATH", cfg):
            resp = client.post("/api/login", json={"email": "a@b.com", "password": "pass"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_valid_credentials_sets_cookie(self, client, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            yaml.dump({"librelinkup": {"email": "a@b.com", "password": "pass"}})
        )
        with patch("src.auth._CONFIG_PATH", cfg):
            resp = client.post("/api/login", json={"email": "a@b.com", "password": "pass"})
        assert "session_token" in resp.cookies

    def test_invalid_credentials_returns_401(self, client, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            yaml.dump({"librelinkup": {"email": "a@b.com", "password": "pass"}})
        )
        with patch("src.auth._CONFIG_PATH", cfg):
            resp = client.post("/api/login", json={"email": "a@b.com", "password": "wrong"})
        assert resp.status_code == 401

    def test_missing_config_returns_401(self, client, tmp_path):
        missing = tmp_path / "config.yaml"
        with patch("src.auth._CONFIG_PATH", missing):
            resp = client.post("/api/login", json={"email": "a@b.com", "password": "pass"})
        assert resp.status_code == 401

    def test_invalid_json_returns_400(self, client):
        resp = client.post(
            "/api/login",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400


# ── /api/logout ───────────────────────────────────────────────────────────────


class TestLogoutEndpoint:
    @pytest.fixture
    def client(self):
        session_manager.clear_all()
        yield TestClient(app)
        session_manager.clear_all()

    def test_logout_returns_200(self, client):
        resp = client.post("/api/logout")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_logout_invalidates_session(self, client):
        token = session_manager.create_session()
        client.cookies.set("session_token", token)
        client.post("/api/logout")
        assert not session_manager.is_valid(token)


# ── /api/setup ────────────────────────────────────────────────────────────────


class TestSetupEndpoint:
    @pytest.fixture
    def client(self, tmp_path):
        session_manager.clear_all()
        # Patch PROJECT_ROOT inside api.py so config.yaml goes to tmp_path
        with patch("src.api.PROJECT_ROOT", tmp_path):
            yield TestClient(app)
        session_manager.clear_all()

    def _minimal_payload(self):
        return {
            "email": "user@example.com",
            "password": "secret",
            "low_threshold": 70,
            "high_threshold": 180,
            "cooldown_minutes": 30,
            "max_reading_age_minutes": 15,
            "notification_type": "none",
        }

    def test_setup_returns_200(self, client):
        resp = client.post("/api/setup", json=self._minimal_payload())
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_setup_sets_cookie(self, client):
        resp = client.post("/api/setup", json=self._minimal_payload())
        assert "session_token" in resp.cookies

    def test_setup_writes_config_yaml(self, client, tmp_path):
        client.post("/api/setup", json=self._minimal_payload())
        cfg_path = tmp_path / "config.yaml"
        assert cfg_path.exists()
        config = yaml.safe_load(cfg_path.read_text())
        assert config["librelinkup"]["email"] == "user@example.com"
        assert config["alerts"]["low_threshold"] == 70
        assert config["alerts"]["high_threshold"] == 180

    def test_setup_with_telegram(self, client, tmp_path):
        payload = self._minimal_payload()
        payload["notification_type"] = "telegram"
        payload["telegram_bot_token"] = "BOT_TOKEN"
        payload["telegram_chat_id"] = "-100123"
        client.post("/api/setup", json=payload)
        config = yaml.safe_load((tmp_path / "config.yaml").read_text())
        outputs = config["outputs"]
        assert any(o["type"] == "telegram" and o["enabled"] for o in outputs)

    def test_setup_with_webhook(self, client, tmp_path):
        payload = self._minimal_payload()
        payload["notification_type"] = "webhook"
        payload["webhook_url"] = "https://example.com/hook"
        client.post("/api/setup", json=payload)
        config = yaml.safe_load((tmp_path / "config.yaml").read_text())
        outputs = config["outputs"]
        assert any(o["type"] == "webhook" and o["enabled"] for o in outputs)

    def test_setup_with_whatsapp(self, client, tmp_path):
        payload = self._minimal_payload()
        payload["notification_type"] = "whatsapp"
        payload["whatsapp_phone_number_id"] = "123"
        payload["whatsapp_access_token"] = "token"
        payload["whatsapp_recipient"] = "521234567890"
        client.post("/api/setup", json=payload)
        config = yaml.safe_load((tmp_path / "config.yaml").read_text())
        outputs = config["outputs"]
        assert any(o["type"] == "whatsapp" and o["enabled"] for o in outputs)

    def test_setup_missing_email_returns_422(self, client):
        payload = self._minimal_payload()
        payload["email"] = ""
        resp = client.post("/api/setup", json=payload)
        assert resp.status_code == 422

    def test_setup_missing_password_returns_422(self, client):
        payload = self._minimal_payload()
        payload["password"] = ""
        resp = client.post("/api/setup", json=payload)
        assert resp.status_code == 422

    def test_setup_invalid_thresholds_returns_422(self, client):
        payload = self._minimal_payload()
        payload["low_threshold"] = 200
        payload["high_threshold"] = 100
        resp = client.post("/api/setup", json=payload)
        assert resp.status_code == 422

    def test_setup_invalid_json_returns_400(self, client):
        resp = client.post(
            "/api/setup",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    def test_setup_config_has_required_defaults(self, client, tmp_path):
        client.post("/api/setup", json=self._minimal_payload())
        config = yaml.safe_load((tmp_path / "config.yaml").read_text())
        assert "monitoring" in config
        assert config["monitoring"]["mode"] == "cron"
        assert "dashboard" in config
        assert config["dashboard"]["enabled"] is True
        assert "logging" in config
        assert "state_file" in config


# ── Auth middleware ───────────────────────────────────────────────────────────


class TestAuthMiddleware:
    """Tests for the auth middleware (requires auth to be enabled)."""

    @pytest.fixture
    def auth_client(self, monkeypatch):
        """TestClient with auth enforcement enabled (no AUTH_DISABLED env var)."""
        monkeypatch.delenv("AUTH_DISABLED", raising=False)
        session_manager.clear_all()
        yield TestClient(app, follow_redirects=False)
        session_manager.clear_all()

    def test_unauthenticated_request_redirects_to_login_when_configured(
        self, auth_client
    ):
        with patch("src.api.is_configured", return_value=True):
            resp = auth_client.get("/")
        assert resp.status_code == 302
        assert resp.headers["location"] == "/login"

    def test_unauthenticated_request_redirects_to_setup_when_not_configured(
        self, auth_client
    ):
        with patch("src.api.is_configured", return_value=False):
            resp = auth_client.get("/")
        assert resp.status_code == 302
        assert resp.headers["location"] == "/setup"

    def test_authenticated_request_passes_through(self, auth_client):
        token = session_manager.create_session()
        auth_client.cookies.set("session_token", token)
        resp = auth_client.get("/api/health")
        assert resp.status_code == 200

    def test_invalid_token_redirects(self, auth_client):
        auth_client.cookies.set("session_token", "invalid_token")
        with patch("src.api.is_configured", return_value=True):
            resp = auth_client.get("/api/health")
        assert resp.status_code == 302

    def test_exempt_setup_status_accessible_without_auth(self, auth_client):
        with patch("src.api.is_configured", return_value=False):
            resp = auth_client.get("/api/setup/status")
        assert resp.status_code == 200

    def test_exempt_login_route_accessible_without_auth(self, auth_client):
        with patch("src.api.is_configured", return_value=True):
            resp = auth_client.get("/login")
        assert resp.status_code == 200

    def test_exempt_setup_route_accessible_without_auth(self, auth_client):
        resp = auth_client.get("/setup")
        assert resp.status_code == 200


# ── /login and /setup page routes ─────────────────────────────────────────────


class TestPageRoutes:
    @pytest.fixture
    def client(self):
        return TestClient(app, follow_redirects=False)

    def test_login_page_redirects_to_setup_when_not_configured(self, client):
        with patch("src.api.is_configured", return_value=False):
            resp = client.get("/login")
        assert resp.status_code == 302
        assert resp.headers["location"] == "/setup"

    def test_login_page_returns_html_when_configured(self, client):
        with patch("src.api.is_configured", return_value=True):
            resp = client.get("/login")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "LibreLinkUp" in resp.text

    def test_setup_page_returns_html(self, client):
        resp = client.get("/setup")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "LibreLinkUp" in resp.text
