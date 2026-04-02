"""Tests for src/auth.py and authentication-related API endpoints."""
import time
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from fastapi.testclient import TestClient

import src.api
import src.auth
from src.api import app
from src.auth import (
    SESSION_TTL,
    SessionManager,
    check_password,
    hash_password,
    is_configured,
    session_manager,
    verify_credentials,
)


@pytest.fixture(autouse=True)
def _isolated_session_manager(tmp_path, monkeypatch):
    """Replace the global session_manager with an isolated SQLite-backed instance
    in a temporary directory so tests never write to the production sessions.db."""
    sm = SessionManager(db_path=str(tmp_path / "test_sessions.db"))
    monkeypatch.setattr(src.auth, "session_manager", sm)
    monkeypatch.setattr(src.api, "session_manager", sm)
    # Also update the name bound at module level in *this* test file so that
    # the unqualified ``session_manager`` references inside test methods resolve
    # to the isolated instance.
    import tests.test_auth as _this_module
    monkeypatch.setattr(_this_module, "session_manager", sm)
    yield sm


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

    def test_expired_token_is_invalid(self, tmp_path):
        mgr = SessionManager(db_path=str(tmp_path / "mgr_test.db"))
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


# ── hash_password / check_password ───────────────────────────────────────────


class TestPasswordHashing:
    def test_hash_returns_string(self):
        h = hash_password("mysecret")
        assert isinstance(h, str)

    def test_hash_format(self):
        h = hash_password("mysecret")
        parts = h.split(":")
        assert parts[0] == "pbkdf2"
        assert parts[1] == "sha256"
        assert len(parts) == 5

    def test_check_password_correct(self):
        h = hash_password("mysecret")
        assert check_password("mysecret", h)

    def test_check_password_wrong(self):
        h = hash_password("mysecret")
        assert not check_password("wrongpassword", h)

    def test_two_hashes_differ(self):
        """Each call produces a different hash (random salt)."""
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2

    def test_check_password_invalid_hash(self):
        assert not check_password("anything", "notahash")

    def test_check_password_empty_hash(self):
        assert not check_password("anything", "")


# ── verify_credentials ────────────────────────────────────────────────────────


class TestVerifyCredentials:
    def _make_config(self, tmp_path, username: str, password: str) -> Path:
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            yaml.dump(
                {
                    "dashboard_auth": {
                        "username": username,
                        "password_hash": hash_password(password),
                    }
                }
            )
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

    def test_wrong_username(self, tmp_path):
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

    def test_missing_dashboard_auth_section_returns_false(self, tmp_path):
        """Config without dashboard_auth section must not authenticate anyone."""
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            yaml.dump({"librelinkup": {"email": "a@b.com", "password": "pass"}})
        )
        with patch("src.auth._CONFIG_PATH", cfg):
            assert not verify_credentials("a@b.com", "pass")


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
        with patch("src.api.is_setup_complete", return_value=True):
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

    def _make_dashboard_config(self, tmp_path, username: str, password: str) -> Path:
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            yaml.dump(
                {
                    "dashboard_auth": {
                        "username": username,
                        "password_hash": hash_password(password),
                    }
                }
            )
        )
        return cfg

    def test_valid_credentials_returns_200(self, client, tmp_path):
        cfg = self._make_dashboard_config(tmp_path, "a@b.com", "pass")
        with patch("src.auth._CONFIG_PATH", cfg):
            resp = client.post("/api/login", json={"email": "a@b.com", "password": "pass"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_valid_credentials_sets_cookie(self, client, tmp_path):
        cfg = self._make_dashboard_config(tmp_path, "a@b.com", "pass")
        with patch("src.auth._CONFIG_PATH", cfg):
            resp = client.post("/api/login", json={"email": "a@b.com", "password": "pass"})
        assert "session_token" in resp.cookies

    def test_login_with_username_field(self, client, tmp_path):
        """The 'username' field is accepted as an alias for 'email'."""
        cfg = self._make_dashboard_config(tmp_path, "admin", "pass")
        with patch("src.auth._CONFIG_PATH", cfg):
            resp = client.post("/api/login", json={"username": "admin", "password": "pass"})
        assert resp.status_code == 200

    def test_invalid_credentials_returns_401(self, client, tmp_path):
        cfg = self._make_dashboard_config(tmp_path, "a@b.com", "pass")
        with patch("src.auth._CONFIG_PATH", cfg):
            resp = client.post("/api/login", json={"email": "a@b.com", "password": "wrong"})
        assert resp.status_code == 401

    def test_librelinkup_password_not_accepted_as_dashboard_login(self, client, tmp_path):
        """LibreLinkUp plaintext password must NOT work for dashboard login."""
        from src.auth import verify_credentials as _verify

        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            yaml.dump(
                {
                    "librelinkup": {"email": "a@b.com", "password": "llup_pass"},
                    "dashboard_auth": {
                        "username": "a@b.com",
                        "password_hash": hash_password("dashboard_pass"),
                    },
                }
            )
        )
        with patch("src.auth._CONFIG_PATH", cfg):
            # LibreLinkUp password should not work for dashboard login
            assert not _verify("a@b.com", "llup_pass")
            # Dashboard password should work
            assert _verify("a@b.com", "dashboard_pass")

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
            "dashboard_password": "dashpass1",
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

    def test_setup_stores_dashboard_auth_separately(self, client, tmp_path):
        """dashboard_auth section must be present and password stored as hash."""
        client.post("/api/setup", json=self._minimal_payload())
        config = yaml.safe_load((tmp_path / "config.yaml").read_text())
        dash_auth = config.get("dashboard_auth", {})
        assert dash_auth.get("username") == "user@example.com"
        # Password must be stored as a hash, never plain text
        stored_hash = dash_auth.get("password_hash", "")
        assert stored_hash.startswith("pbkdf2:sha256:")
        assert stored_hash != "dashpass1"
        # Verify the hash validates correctly
        assert check_password("dashpass1", stored_hash)

    def test_setup_librelinkup_password_not_used_as_dashboard_password(self, client, tmp_path):
        """LibreLinkUp password must not be used verbatim as the dashboard password."""
        client.post("/api/setup", json=self._minimal_payload())
        config = yaml.safe_load((tmp_path / "config.yaml").read_text())
        # LibreLinkUp section must store the password encrypted, not plain text
        llu_stored = config["librelinkup"]["password"]
        assert llu_stored.startswith("encrypted:")
        assert llu_stored != "secret"
        # Dashboard hash must NOT validate with the LibreLinkUp password
        stored_hash = config["dashboard_auth"]["password_hash"]
        assert not check_password("secret", stored_hash)
        # Only the dedicated dashboard_password validates
        assert check_password("dashpass1", stored_hash)

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

    def test_setup_missing_dashboard_password_returns_422(self, client):
        payload = self._minimal_payload()
        payload["dashboard_password"] = ""
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

    def test_setup_no_notification_sets_mode_dashboard(self, client, tmp_path):
        """When no notification output is selected, mode should be 'dashboard'."""
        client.post("/api/setup", json=self._minimal_payload())
        config = yaml.safe_load((tmp_path / "config.yaml").read_text())
        assert config["monitoring"]["mode"] == "dashboard"
        # No outputs at all (no disabled placeholder)
        assert config["outputs"] == []

    def test_setup_with_notification_sets_mode_cron(self, client, tmp_path):
        """When a notification output is selected, mode should be 'cron'."""
        payload = self._minimal_payload()
        payload["notification_type"] = "telegram"
        payload["telegram_bot_token"] = "TOK"
        payload["telegram_chat_id"] = "-1"
        client.post("/api/setup", json=payload)
        config = yaml.safe_load((tmp_path / "config.yaml").read_text())
        assert config["monitoring"]["mode"] == "cron"

    def test_setup_config_has_required_defaults(self, client, tmp_path):
        client.post("/api/setup", json=self._minimal_payload())
        config = yaml.safe_load((tmp_path / "config.yaml").read_text())
        assert "monitoring" in config
        assert "dashboard" in config
        assert config["dashboard"]["enabled"] is True
        assert "logging" in config
        assert "state_file" in config

    def test_setup_encrypts_librelinkup_password(self, client, tmp_path):
        """After POST /api/setup, the LibreLinkUp password must be encrypted in config.yaml."""
        client.post("/api/setup", json=self._minimal_payload())
        config = yaml.safe_load((tmp_path / "config.yaml").read_text())
        stored = config["librelinkup"]["password"]
        assert stored.startswith("encrypted:")
        assert stored != "secret"

    def test_setup_config_has_restricted_permissions(self, client, tmp_path):
        """After POST /api/setup, config.yaml must have permissions 0600."""
        import stat as _stat
        client.post("/api/setup", json=self._minimal_payload())
        cfg_path = tmp_path / "config.yaml"
        mode = cfg_path.stat().st_mode
        assert mode & _stat.S_IRUSR
        assert mode & _stat.S_IWUSR
        assert not (mode & _stat.S_IRGRP)
        assert not (mode & _stat.S_IROTH)


# ── Auth middleware ───────────────────────────────────────────────────────────


class TestAuthMiddleware:
    """Tests for the auth middleware (requires auth to be enabled)."""

    @pytest.fixture
    def auth_client(self, monkeypatch):
        """TestClient with auth enforcement enabled (no AUTH_DISABLED env var)."""
        monkeypatch.delenv("AUTH_DISABLED", raising=False)
        import src.api as _api_module
        monkeypatch.setattr(_api_module, "_ALLOW_AUTH_DISABLED", False)
        session_manager.clear_all()
        yield TestClient(app, follow_redirects=False)
        session_manager.clear_all()

    def test_unauthenticated_request_redirects_to_login_when_configured(
        self, auth_client
    ):
        with patch("src.api.is_setup_complete", return_value=True):
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
        with patch("src.api.is_setup_complete", return_value=True):
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
        with patch("src.api.is_setup_complete", return_value=True):
            resp = client.get("/login")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "panel de control" in resp.text

    def test_setup_page_returns_html(self, client):
        resp = client.get("/setup")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "LibreLinkUp" in resp.text


# ── Login rate limiting ────────────────────────────────────────────────────────


class TestLoginRateLimit:
    """Tests for brute-force protection on the /api/login endpoint."""

    @pytest.fixture
    def client(self):
        return TestClient(app, follow_redirects=False)

    @pytest.fixture(autouse=True)
    def _reset_rate_limiter(self):
        """Clear any accumulated failed-login state before each test."""
        yield
        session_manager.clear_all_login_attempts()

    def test_rate_limit_after_max_attempts(self, client, tmp_path):
        """After MAX failed attempts the next request must return 429."""
        import src.api as _api

        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            yaml.dump(
                {
                    "dashboard_auth": {
                        "username": "user",
                        "password_hash": hash_password("secret"),
                    }
                }
            )
        )
        with patch("src.auth._CONFIG_PATH", cfg):
            # Exhaust the allowed attempts
            for _ in range(_api._LOGIN_MAX_ATTEMPTS):
                resp = client.post(
                    "/api/login",
                    json={"username": "user", "password": "wrong"},
                )
                assert resp.status_code == 401

            # The next attempt must be blocked
            resp = client.post(
                "/api/login",
                json={"username": "user", "password": "wrong"},
            )
        assert resp.status_code == 429

    def test_successful_login_resets_counter(self, client, tmp_path):
        """A successful login clears the failed-attempt counter for that IP."""
        import src.api as _api

        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            yaml.dump(
                {
                    "dashboard_auth": {
                        "username": "user",
                        "password_hash": hash_password("correct"),
                    }
                }
            )
        )
        with patch("src.auth._CONFIG_PATH", cfg):
            # Accumulate some failures
            for _ in range(_api._LOGIN_MAX_ATTEMPTS - 1):
                client.post(
                    "/api/login",
                    json={"username": "user", "password": "wrong"},
                )

            # Successful login should reset the counter
            resp = client.post(
                "/api/login",
                json={"username": "user", "password": "correct"},
            )
            assert resp.status_code == 200

            # Immediately after, a wrong password should NOT be rate-limited (counter was reset)
            for _ in range(_api._LOGIN_MAX_ATTEMPTS):
                resp = client.post(
                    "/api/login",
                    json={"username": "user", "password": "wrong"},
                )
                assert resp.status_code == 401  # still within limit after reset


# ── SessionManager login attempts (Issue 2.2) ─────────────────────────────────


class TestLoginAttempts:
    def test_record_and_count_failed_logins(self):
        session_manager.clear_all_login_attempts()
        session_manager.record_failed_login("192.168.1.1")
        session_manager.record_failed_login("192.168.1.1")
        count = session_manager.get_recent_failed_logins("192.168.1.1", window_seconds=600)
        assert count == 2

    def test_count_ignores_other_ips(self):
        session_manager.clear_all_login_attempts()
        session_manager.record_failed_login("10.0.0.1")
        count = session_manager.get_recent_failed_logins("10.0.0.2", window_seconds=600)
        assert count == 0

    def test_clear_failed_logins(self):
        session_manager.clear_all_login_attempts()
        session_manager.record_failed_login("1.2.3.4")
        session_manager.clear_failed_logins("1.2.3.4")
        assert session_manager.get_recent_failed_logins("1.2.3.4", window_seconds=600) == 0

    def test_cleanup_old_login_attempts(self):
        import time as _time
        session_manager.clear_all_login_attempts()
        session_manager.record_failed_login("5.6.7.8")
        # Cleanup with window of 0 seconds removes the just-inserted record
        with patch("src.auth.time") as mock_time:
            mock_time.time.return_value = _time.time() + 700
            removed = session_manager.cleanup_old_login_attempts(window_seconds=600)
        assert removed >= 1


# ── Issue 1.1: Setup security — block reconfiguration without auth ─────────────


class TestSetupSecurity:
    @pytest.fixture
    def client(self, tmp_path):
        session_manager.clear_all()
        with patch("src.api.PROJECT_ROOT", tmp_path):
            yield TestClient(app)
        session_manager.clear_all()

    def _minimal_payload(self):
        return {
            "email": "user@example.com",
            "password": "secret",
            "dashboard_password": "dashpass1",
            "low_threshold": 70,
            "high_threshold": 180,
            "cooldown_minutes": 30,
            "max_reading_age_minutes": 15,
            "notification_type": "none",
        }

    def test_first_setup_allowed_without_auth(self, client):
        with patch("src.api.is_configured", return_value=False):
            resp = client.post("/api/setup", json=self._minimal_payload())
        assert resp.status_code == 200

    def test_reconfiguration_blocked_without_session(self, client):
        with patch("src.api.is_configured", return_value=True):
            resp = client.post("/api/setup", json=self._minimal_payload())
        assert resp.status_code == 403
        assert "configurado" in resp.json()["detail"].lower()

    def test_reconfiguration_allowed_with_valid_session(self, client, tmp_path):
        token = session_manager.create_session()
        client.cookies.set("session_token", token)
        with patch("src.api.is_configured", return_value=True):
            with patch("src.api.PROJECT_ROOT", tmp_path):
                resp = client.post("/api/setup", json=self._minimal_payload())
        assert resp.status_code == 200

    def test_reconfiguration_blocked_with_invalid_session(self, client):
        client.cookies.set("session_token", "invalid-garbage-token")
        with patch("src.api.is_configured", return_value=True):
            resp = client.post("/api/setup", json=self._minimal_payload())
        assert resp.status_code == 403


# ── Issue 2.3: Password length validation ─────────────────────────────────────


class TestPasswordLengthValidation:
    @pytest.fixture
    def client(self, tmp_path):
        with patch("src.api.PROJECT_ROOT", tmp_path):
            yield TestClient(app)

    def _payload_with_password(self, pwd: str):
        return {
            "email": "user@example.com",
            "password": "librelinkuppass",
            "dashboard_password": pwd,
            "low_threshold": 70,
            "high_threshold": 180,
            "cooldown_minutes": 30,
            "max_reading_age_minutes": 15,
            "notification_type": "none",
        }

    def test_short_password_returns_422(self, client):
        resp = client.post("/api/setup", json=self._payload_with_password("short1"))
        assert resp.status_code == 422
        assert "8 caracteres" in resp.json()["detail"]

    def test_seven_char_password_returns_422(self, client):
        resp = client.post("/api/setup", json=self._payload_with_password("1234567"))
        assert resp.status_code == 422

    def test_eight_char_password_accepted(self, client):
        with patch("src.api.is_configured", return_value=False):
            resp = client.post("/api/setup", json=self._payload_with_password("12345678"))
        assert resp.status_code == 200

    def test_long_password_accepted(self, client):
        with patch("src.api.is_configured", return_value=False):
            resp = client.post("/api/setup", json=self._payload_with_password("a-very-long-password-ok"))
        assert resp.status_code == 200


# ── Issue 2.4: Region selector ────────────────────────────────────────────────


class TestRegionSelector:
    @pytest.fixture
    def client(self, tmp_path):
        with patch("src.api.PROJECT_ROOT", tmp_path):
            yield TestClient(app)

    def _payload_with_region(self, region: str):
        return {
            "email": "user@example.com",
            "password": "librelinkuppass",
            "dashboard_password": "dashpass1",
            "region": region,
            "low_threshold": 70,
            "high_threshold": 180,
            "cooldown_minutes": 30,
            "max_reading_age_minutes": 15,
            "notification_type": "none",
        }

    def test_valid_region_eu_accepted(self, client):
        with patch("src.api.is_configured", return_value=False):
            resp = client.post("/api/setup", json=self._payload_with_region("EU"))
        assert resp.status_code == 200

    def test_valid_region_us_accepted(self, client, tmp_path):
        with patch("src.api.is_configured", return_value=False):
            with patch("src.api.PROJECT_ROOT", tmp_path):
                resp = client.post("/api/setup", json=self._payload_with_region("US"))
        assert resp.status_code == 200

    def test_invalid_region_returns_422(self, client):
        resp = client.post("/api/setup", json=self._payload_with_region("XX"))
        assert resp.status_code == 422
        assert "Región no válida" in resp.json()["detail"]

    def test_region_saved_in_config(self, client, tmp_path):
        with patch("src.api.is_configured", return_value=False):
            with patch("src.api.PROJECT_ROOT", tmp_path):
                client.post("/api/setup", json=self._payload_with_region("US"))
        config = yaml.safe_load((tmp_path / "config.yaml").read_text())
        assert config["librelinkup"]["region"] == "US"

    def test_default_region_is_eu_when_not_provided(self, client, tmp_path):
        payload = {
            "email": "user@example.com",
            "password": "librelinkuppass",
            "dashboard_password": "dashpass1",
            "low_threshold": 70,
            "high_threshold": 180,
            "cooldown_minutes": 30,
            "max_reading_age_minutes": 15,
            "notification_type": "none",
        }
        with patch("src.api.is_configured", return_value=False):
            with patch("src.api.PROJECT_ROOT", tmp_path):
                client.post("/api/setup", json=payload)
        config = yaml.safe_load((tmp_path / "config.yaml").read_text())
        assert config["librelinkup"]["region"] == "EU"


# ── CSRF protection ───────────────────────────────────────────────────────────


class TestCSRFProtection:
    """Tests for CSRF validation on sensitive POST endpoints.

    These tests enable real auth (disable the global bypass) and verify that
    POST requests without a valid CSRF token are rejected with 403.
    """

    @pytest.fixture
    def csrf_client(self, monkeypatch):
        """TestClient with auth AND CSRF enforcement enabled."""
        import src.api as _api_module
        monkeypatch.setattr(_api_module, "_ALLOW_AUTH_DISABLED", False)
        session_manager.clear_all()
        yield TestClient(app, follow_redirects=False)
        session_manager.clear_all()

    def test_logout_without_csrf_returns_403(self, csrf_client):
        """POST /api/logout without X-CSRF-Token must be rejected."""
        token = session_manager.create_session()
        csrf_client.cookies.set("session_token", token)
        resp = csrf_client.post("/api/logout")
        assert resp.status_code == 403

    def test_logout_with_mismatched_csrf_returns_403(self, csrf_client):
        """POST /api/logout with a wrong X-CSRF-Token must be rejected."""
        token = session_manager.create_session()
        csrf_client.cookies.set("session_token", token)
        csrf_client.cookies.set("csrf_token", "correct-token")
        resp = csrf_client.post("/api/logout", headers={"X-CSRF-Token": "wrong-token"})
        assert resp.status_code == 403

    def test_logout_with_valid_csrf_returns_200(self, csrf_client):
        """POST /api/logout with matching CSRF cookie and header must succeed."""
        token = session_manager.create_session()
        csrf_token = "test-csrf-token-abc123"
        csrf_client.cookies.set("session_token", token)
        csrf_client.cookies.set("csrf_token", csrf_token)
        resp = csrf_client.post("/api/logout", headers={"X-CSRF-Token": csrf_token})
        assert resp.status_code == 200

    def test_login_sets_csrf_cookie(self, csrf_client, tmp_path):
        """Successful login must set both session_token and csrf_token cookies."""
        with patch("src.api.verify_credentials", return_value=True):
            with patch("src.api.PROJECT_ROOT", tmp_path):
                resp = csrf_client.post(
                    "/api/login",
                    json={"username": "admin", "password": "pass"},
                )
        assert resp.status_code == 200
        assert "csrf_token" in resp.cookies

    def test_setup_sets_csrf_cookie(self, csrf_client, tmp_path):
        """Successful setup must set a csrf_token cookie."""
        payload = {
            "email": "user@example.com",
            "password": "secret",
            "dashboard_password": "dashpass1",
            "low_threshold": 70,
            "high_threshold": 180,
            "cooldown_minutes": 30,
            "max_reading_age_minutes": 15,
            "notification_type": "none",
        }
        with patch("src.api.PROJECT_ROOT", tmp_path):
            resp = csrf_client.post("/api/setup", json=payload)
        assert resp.status_code == 200
        assert "csrf_token" in resp.cookies


# ── Setup: output field validation ────────────────────────────────────────────


class TestSetupOutputValidation:
    """Verify that missing required fields for each output type are rejected."""

    @pytest.fixture
    def client(self, tmp_path):
        session_manager.clear_all()
        with patch("src.api.PROJECT_ROOT", tmp_path):
            yield TestClient(app)
        session_manager.clear_all()

    def _base(self):
        return {
            "email": "user@example.com",
            "password": "secret",
            "dashboard_password": "dashpass1",
            "low_threshold": 70,
            "high_threshold": 180,
            "cooldown_minutes": 30,
            "max_reading_age_minutes": 15,
        }

    def test_telegram_missing_bot_token_returns_422(self, client):
        payload = {**self._base(), "notification_type": "telegram", "telegram_chat_id": "-1"}
        resp = client.post("/api/setup", json=payload)
        assert resp.status_code == 422

    def test_telegram_missing_chat_id_returns_422(self, client):
        payload = {**self._base(), "notification_type": "telegram", "telegram_bot_token": "TOK"}
        resp = client.post("/api/setup", json=payload)
        assert resp.status_code == 422

    def test_webhook_missing_url_returns_422(self, client):
        payload = {**self._base(), "notification_type": "webhook"}
        resp = client.post("/api/setup", json=payload)
        assert resp.status_code == 422

    def test_whatsapp_missing_fields_returns_422(self, client):
        payload = {**self._base(), "notification_type": "whatsapp", "whatsapp_phone_number_id": "123"}
        resp = client.post("/api/setup", json=payload)
        assert resp.status_code == 422


# ── Setup: config validated before persisting ─────────────────────────────────


class TestSetupConfigValidation:
    """Verify that the config is validated via schema before being written."""

    @pytest.fixture
    def client(self, tmp_path):
        session_manager.clear_all()
        with patch("src.api.PROJECT_ROOT", tmp_path):
            yield TestClient(app)
        session_manager.clear_all()

    def test_valid_config_is_persisted(self, client, tmp_path):
        payload = {
            "email": "user@example.com",
            "password": "secret",
            "dashboard_password": "dashpass1",
            "low_threshold": 70,
            "high_threshold": 180,
            "cooldown_minutes": 30,
            "max_reading_age_minutes": 15,
            "notification_type": "none",
        }
        with patch("src.api.PROJECT_ROOT", tmp_path):
            resp = client.post("/api/setup", json=payload)
        assert resp.status_code == 200
        assert (tmp_path / "config.yaml").exists()

    def test_config_persisted_as_safe_yaml(self, client, tmp_path):
        """Config must be written with yaml.safe_dump (no Python tags)."""
        import yaml as _yaml

        payload = {
            "email": "user@example.com",
            "password": "secret",
            "dashboard_password": "dashpass1",
            "low_threshold": 70,
            "high_threshold": 180,
            "cooldown_minutes": 30,
            "max_reading_age_minutes": 15,
            "notification_type": "none",
        }
        with patch("src.api.PROJECT_ROOT", tmp_path):
            client.post("/api/setup", json=payload)
        content = (tmp_path / "config.yaml").read_text()
        # yaml.safe_dump must not emit Python-specific tags like !!python/
        assert "!!python/" not in content
        # Must be parseable by safe_load without error
        loaded = _yaml.safe_load(content)
        assert isinstance(loaded, dict)
