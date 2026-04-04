"""Tests for FastAPI endpoints in src/api.py."""
import json

import pytest
from fastapi.testclient import TestClient

import src.api as api_module
from src.api import app, _get_color

# ── Minimal config used to make alert_engine calls succeed ────────────────────

_MINIMAL_CONFIG = {
    "api": {},  # cache_file will be injected by tmp_cache fixture
    "alerts": {
        "low_threshold": 70,
        "high_threshold": 180,
        "trend": {"enabled": False},
    },
}


# ── Shared fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    """Disable auth middleware and reset cache state before/after each test."""
    # Patch the module-level flag that the auth middleware reads at request time
    monkeypatch.setattr(api_module, "_ALLOW_AUTH_DISABLED", True)
    # Reset in-memory cache
    with api_module._cache_lock:
        api_module._readings_cache.clear()
    api_module._last_mtime = 0.0
    yield
    with api_module._cache_lock:
        api_module._readings_cache.clear()
    api_module._last_mtime = 0.0


@pytest.fixture
def tmp_cache(tmp_path, monkeypatch):
    """Create a temporary cache file and patch api.py to use it.

    Provides a ``pathlib.Path`` pointing to the temp ``readings_cache.json``.
    The fixture also injects a minimal config so that ``alert_engine`` calls
    inside ``_load_and_enrich_cache()`` do not raise ``KeyError``.
    """
    cache_file = tmp_path / "readings_cache.json"
    cache_file.write_text('{"readings": [], "updated_at": null}')
    config = dict(_MINIMAL_CONFIG)
    config["api"] = {"cache_file": str(cache_file)}
    monkeypatch.setattr(api_module, "_config", config)
    api_module._last_mtime = 0.0
    return cache_file


def _write_readings(cache_file, readings):
    """Write *readings* to *cache_file* and reset mtime tracker to force reload."""
    payload = {"readings": readings, "updated_at": "2024-01-01T00:00:00+00:00"}
    cache_file.write_text(json.dumps(payload))
    api_module._last_mtime = 0.0


@pytest.fixture
def client():
    return TestClient(app)


# ── /api/health ──────────────────────────────────────────────────────────────

class TestHealthEndpoint:
    def test_returns_200(self, client, tmp_cache):
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_status_is_ok(self, client, tmp_cache):
        resp = client.get("/api/health")
        assert resp.json()["status"] == "ok"

    def test_has_updated_at(self, client, tmp_cache):
        resp = client.get("/api/health")
        assert "updated_at" in resp.json()

    def test_patient_count_zero_when_empty(self, client, tmp_cache):
        resp = client.get("/api/health")
        assert resp.json()["patient_count"] == 0

    def test_patient_count_counts_cache(self, client, tmp_cache):
        _write_readings(tmp_cache, [
            {"patient_id": "p1", "patient_name": "Ana", "value": 100, "trend_arrow": "→"},
            {"patient_id": "p2", "patient_name": "Juan", "value": 120, "trend_arrow": "→"},
        ])
        resp = client.get("/api/health")
        assert resp.json()["patient_count"] == 2

    def test_cache_age_seconds_is_null(self, client, tmp_cache):
        """Dashboard API always returns null for cache_age_seconds (in-memory)."""
        resp = client.get("/api/health")
        assert resp.json()["cache_age_seconds"] is None


# ── /api/patients ────────────────────────────────────────────────────────────

class TestPatientsListEndpoint:
    def test_returns_200(self, client, tmp_cache):
        resp = client.get("/api/patients")
        assert resp.status_code == 200

    def test_empty_cache_returns_empty_list(self, client, tmp_cache):
        resp = client.get("/api/patients")
        data = resp.json()
        assert data["patients"] == []
        assert data["count"] == 0

    def test_returns_all_patients(self, client, tmp_cache):
        _write_readings(tmp_cache, [
            {"patient_id": "abc", "patient_name": "Ana", "value": 100, "trend_arrow": "→"},
            {"patient_id": "xyz", "patient_name": "Juan", "value": 120, "trend_arrow": "→"},
        ])
        resp = client.get("/api/patients")
        data = resp.json()
        assert data["count"] == 2
        ids = {p["patient_id"] for p in data["patients"]}
        assert ids == {"abc", "xyz"}


# ── /api/patients/{patient_id} ───────────────────────────────────────────────

class TestPatientDetailEndpoint:
    def test_404_for_unknown_patient(self, client, tmp_cache):
        resp = client.get("/api/patients/nonexistent")
        assert resp.status_code == 404

    def test_returns_patient_data(self, client, tmp_cache):
        _write_readings(tmp_cache, [
            {"patient_id": "p42", "patient_name": "María", "value": 120, "trend_arrow": "→"},
        ])
        resp = client.get("/api/patients/p42")
        assert resp.status_code == 200
        data = resp.json()
        assert data["patient_id"] == "p42"
        assert data["patient_name"] == "María"

    def test_404_detail_message(self, client, tmp_cache):
        resp = client.get("/api/patients/no-such-id")
        assert "not found" in resp.json()["detail"].lower()


# ── / (dashboard HTML) ───────────────────────────────────────────────────────

class TestDashboardEndpoint:
    def test_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_content_type_is_html(self, client):
        resp = client.get("/")
        assert "text/html" in resp.headers["content-type"]

    def test_html_contains_title(self, client):
        resp = client.get("/")
        assert "Monitor de Glucosa Familiar" in resp.text

    def test_html_contains_disclaimer(self, client):
        resp = client.get("/")
        assert "dispositivo médico" in resp.text

    def test_html_contains_fetch_script(self, client):
        resp = client.get("/")
        assert "fetchPatients" in resp.text


# ── _get_color helper ────────────────────────────────────────────────────────

class TestGetColor:
    def test_low_level_returns_red(self):
        assert _get_color("low", "normal") == "red"

    def test_high_level_returns_red(self):
        assert _get_color("high", "normal") == "red"

    def test_falling_fast_trend_returns_red(self):
        assert _get_color("normal", "falling_fast") == "red"

    def test_falling_trend_returns_yellow(self):
        assert _get_color("normal", "falling") == "yellow"

    def test_rising_fast_trend_returns_yellow(self):
        assert _get_color("normal", "rising_fast") == "yellow"

    def test_normal_level_and_trend_returns_green(self):
        assert _get_color("normal", "normal") == "green"

    def test_normal_level_stable_trend_returns_green(self):
        assert _get_color("normal", "stable") == "green"

    def test_normal_level_rising_trend_returns_green(self):
        # "rising" alone (not "rising_fast") → green (approaching but not urgent)
        assert _get_color("normal", "rising") == "green"


# ── Cache file loading behaviour ─────────────────────────────────────────────

class TestLoadAndEnrichCache:
    """Verify file-based cache loading and enrichment."""

    def test_missing_file_yields_empty_cache(self, tmp_path, monkeypatch):
        """When the cache file does not exist the cache must be empty."""
        config = dict(_MINIMAL_CONFIG)
        config["api"] = {"cache_file": str(tmp_path / "nonexistent.json")}
        monkeypatch.setattr(api_module, "_config", config)
        api_module._last_mtime = 0.0

        api_module._load_and_enrich_cache()

        with api_module._cache_lock:
            assert api_module._readings_cache == {}

    def test_valid_file_populates_cache(self, tmp_cache):
        """Readings from the cache file are loaded and enriched."""
        _write_readings(tmp_cache, [
            {"patient_id": "p1", "patient_name": "Ana", "value": 100, "trend_arrow": "→"},
        ])
        api_module._load_and_enrich_cache()

        with api_module._cache_lock:
            assert "p1" in api_module._readings_cache
            entry = api_module._readings_cache["p1"]
        assert entry["glucose_value"] == 100
        assert "level" in entry
        assert "trend_alert" in entry
        assert "color" in entry
        assert "fetched_at" in entry

    def test_unchanged_file_not_reloaded(self, tmp_cache, monkeypatch):
        """A second call with the same mtime must not re-read the file."""
        _write_readings(tmp_cache, [
            {"patient_id": "p1", "patient_name": "Ana", "value": 100, "trend_arrow": "→"},
        ])
        api_module._load_and_enrich_cache()

        # Modify in-memory cache to detect if reload happens
        with api_module._cache_lock:
            api_module._readings_cache["sentinel"] = {"patient_id": "sentinel"}

        # Call again without touching the file — mtime unchanged
        api_module._load_and_enrich_cache()

        with api_module._cache_lock:
            assert "sentinel" in api_module._readings_cache, (
                "Cache was unexpectedly reloaded despite unchanged mtime"
            )

    def test_removed_patient_evicted_on_new_file(self, tmp_cache):
        """A patient absent from the new cache file must be evicted."""
        _write_readings(tmp_cache, [
            {"patient_id": "p1", "patient_name": "A", "value": 100, "trend_arrow": "→"},
            {"patient_id": "p2", "patient_name": "B", "value": 120, "trend_arrow": "→"},
        ])
        api_module._load_and_enrich_cache()

        # Overwrite the file with only p1
        _write_readings(tmp_cache, [
            {"patient_id": "p1", "patient_name": "A", "value": 100, "trend_arrow": "→"},
        ])
        api_module._load_and_enrich_cache()

        with api_module._cache_lock:
            assert "p1" in api_module._readings_cache
            assert "p2" not in api_module._readings_cache, "Ghost patient must be evicted"

    def test_corrupt_json_clears_cache(self, tmp_cache):
        """A file with invalid JSON must result in an empty cache."""
        _write_readings(tmp_cache, [
            {"patient_id": "p1", "patient_name": "A", "value": 100, "trend_arrow": "→"},
        ])
        api_module._load_and_enrich_cache()

        # Corrupt the file
        tmp_cache.write_text("not valid json{{{")
        api_module._last_mtime = 0.0
        api_module._load_and_enrich_cache()

        with api_module._cache_lock:
            assert api_module._readings_cache == {}



# ── PWA auth-exempt ──────────────────────────────────────────────────────────

class TestPWAAuthExempt:
    """Verify that PWA static assets are accessible without a session cookie."""

    @pytest.fixture
    def auth_client(self, monkeypatch):
        """Return a TestClient with real auth enforcement enabled."""
        monkeypatch.setattr(api_module, "_ALLOW_AUTH_DISABLED", False)
        monkeypatch.setattr("src.api.is_configured", lambda: True)
        monkeypatch.setattr("src.api.is_setup_complete", lambda: True)
        return TestClient(app, raise_server_exceptions=True)

    def test_manifest_accessible_without_auth(self, auth_client):
        resp = auth_client.get("/manifest.json")
        assert resp.status_code == 200

    def test_sw_accessible_without_auth(self, auth_client):
        resp = auth_client.get("/sw.js")
        assert resp.status_code == 200

    def test_icon_accessible_without_auth(self, auth_client):
        resp = auth_client.get("/icons/icon-192.svg")
        assert resp.status_code == 200

    def test_dashboard_requires_auth(self, auth_client):
        resp = auth_client.get("/", follow_redirects=False)
        assert resp.status_code == 302



class TestPWAManifest:
    def test_returns_200(self, client):
        resp = client.get("/manifest.json")
        assert resp.status_code == 200

    def test_content_type_is_json(self, client):
        resp = client.get("/manifest.json")
        assert "json" in resp.headers["content-type"]

    def test_manifest_has_name(self, client):
        resp = client.get("/manifest.json")
        data = resp.json()
        assert data["name"] == "Monitor de Glucosa Familiar"

    def test_manifest_has_standalone_display(self, client):
        resp = client.get("/manifest.json")
        assert resp.json()["display"] == "standalone"

    def test_manifest_has_icons(self, client):
        resp = client.get("/manifest.json")
        assert len(resp.json()["icons"]) >= 2


class TestPWAServiceWorker:
    def test_returns_200(self, client):
        resp = client.get("/sw.js")
        assert resp.status_code == 200

    def test_content_type_is_javascript(self, client):
        resp = client.get("/sw.js")
        assert "javascript" in resp.headers["content-type"]

    def test_sw_contains_cache_name(self, client):
        resp = client.get("/sw.js")
        assert "fgm-shell" in resp.text


class TestPWAIcons:
    def test_icon_192_returns_200(self, client):
        resp = client.get("/icons/icon-192.svg")
        assert resp.status_code == 200

    def test_icon_512_returns_200(self, client):
        resp = client.get("/icons/icon-512.svg")
        assert resp.status_code == 200

    def test_icon_content_type_is_svg(self, client):
        resp = client.get("/icons/icon-192.svg")
        assert "svg" in resp.headers["content-type"]

    def test_unknown_icon_returns_404(self, client):
        resp = client.get("/icons/nonexistent.png")
        assert resp.status_code == 404

    def test_path_traversal_rejected(self, client):
        # /icons/../manifest.json may be normalized by FastAPI to /manifest.json
        # (→ 200 from the manifest route) or rejected entirely (→ 404).
        # In either case, the icons handler never runs and no arbitrary file is
        # exposed — the path traversal is blocked.
        resp = client.get("/icons/../manifest.json")
        assert resp.status_code in (200, 404)

    def test_dotdot_in_filename_rejected(self, client):
        # Directly pass a filename containing '..' to trigger our guard.
        # Whether FastAPI decodes %2F before routing (→ 404) or passes the raw
        # value to the handler (→ 400 from our guard), neither is a successful
        # file read, so both outcomes are acceptable.
        resp = client.get("/icons/..%2Fmanifest.json")
        assert resp.status_code in (400, 404)


class TestPWAHtmlTags:
    """Verify that the HTML pages include PWA meta tags."""

    def test_dashboard_has_manifest_link(self, client):
        resp = client.get("/")
        assert 'rel="manifest"' in resp.text

    def test_dashboard_has_theme_color(self, client):
        resp = client.get("/")
        assert 'name="theme-color"' in resp.text

    def test_dashboard_has_sw_registration(self, client):
        resp = client.get("/")
        assert "serviceWorker" in resp.text

    def test_login_has_manifest_link(self, client):
        resp = client.get("/login")
        assert 'rel="manifest"' in resp.text

    def test_setup_has_manifest_link(self, client):
        resp = client.get("/setup")
        assert 'rel="manifest"' in resp.text


# ── Configuración button on dashboard ────────────────────────────────────────

class TestDashboardConfiguracionButton:
    """Dashboard must render the 'Configuración' button with a gear icon."""

    def test_dashboard_has_configuracion_link(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "/configuracion" in resp.text

    def test_dashboard_configuracion_button_has_label(self, client):
        resp = client.get("/")
        assert "Configuración" in resp.text

    def test_dashboard_configuracion_button_before_salir(self, client):
        resp = client.get("/")
        idx_settings = resp.text.find("/configuracion")
        idx_logout = resp.text.find("logout-btn")
        assert idx_settings != -1, "/configuracion link not found"
        assert idx_logout != -1, "logout-btn not found"
        assert idx_settings < idx_logout, "'Configuración' must appear before 'Salir'"


# ── /configuracion HTML route ────────────────────────────────────────────────

class TestConfiguracionPage:
    """The /configuracion route must serve the settings HTML."""

    def test_authenticated_user_gets_200(self, client):
        resp = client.get("/configuracion")
        assert resp.status_code == 200

    def test_content_type_is_html(self, client):
        resp = client.get("/configuracion")
        assert "text/html" in resp.headers["content-type"]

    def test_page_has_spanish_title(self, client):
        resp = client.get("/configuracion")
        assert "Configuración del sistema" in resp.text

    def test_page_has_librelinkup_section(self, client):
        resp = client.get("/configuracion")
        assert "LibreLinkUp" in resp.text

    def test_page_has_alertas_section(self, client):
        resp = client.get("/configuracion")
        assert "Alertas" in resp.text

    def test_page_has_notificaciones_section(self, client):
        resp = client.get("/configuracion")
        assert "Notificaciones" in resp.text

    def test_page_has_back_link(self, client):
        resp = client.get("/configuracion")
        assert "Volver al dashboard" in resp.text

    def test_unauthenticated_user_is_redirected(self, client, monkeypatch):
        import src.api as api_module
        monkeypatch.setattr(api_module, "_ALLOW_AUTH_DISABLED", False)
        from src.setup_status import is_setup_complete
        monkeypatch.setattr("src.api.is_setup_complete", lambda: True)
        monkeypatch.setattr("src.api.is_configured", lambda: True)
        resp = client.get("/configuracion", follow_redirects=False)
        assert resp.status_code in (302, 307)
        assert "/login" in resp.headers.get("location", "")


# ── GET /api/configuracion ───────────────────────────────────────────────────

class TestApiGetConfiguracion:
    """GET /api/configuracion returns masked config."""

    @pytest.fixture(autouse=True)
    def with_config(self, monkeypatch):
        import src.api as api_module
        from src.crypto import encrypt_value
        monkeypatch.setattr(api_module, "_config", {
            "librelinkup": {
                "email": "test@example.com",
                "password": encrypt_value("mypassword"),
                "region": "EU",
            },
            "alerts": {
                "low_threshold": 70,
                "high_threshold": 180,
                "cooldown_minutes": 20,
                "max_reading_age_minutes": 15,
            },
            "outputs": [
                {
                    "type": "telegram",
                    "enabled": True,
                    "bot_token": "abc123",
                    "chat_id": "111222",
                }
            ],
        })

    def test_returns_200(self, client):
        resp = client.get("/api/configuracion")
        assert resp.status_code == 200

    def test_email_returned(self, client):
        resp = client.get("/api/configuracion")
        assert resp.json()["librelinkup"]["email"] == "test@example.com"

    def test_password_not_exposed(self, client):
        resp = client.get("/api/configuracion")
        data = resp.json()
        # The actual encrypted/plaintext password value must not be in the response
        ll = data.get("librelinkup", {})
        # No 'password' key with a plaintext/encrypted value — only has_password bool
        assert "password" not in ll, "Raw password key must not be in librelinkup response"
        # has_password should be True
        assert ll["has_password"] is True

    def test_alert_thresholds_returned(self, client):
        resp = client.get("/api/configuracion")
        a = resp.json()["alerts"]
        assert a["low_threshold"] == 70
        assert a["high_threshold"] == 180

    def test_telegram_chat_id_returned(self, client):
        resp = client.get("/api/configuracion")
        tg = resp.json()["telegram"]
        assert tg["chat_id"] == "111222"

    def test_telegram_bot_token_not_exposed(self, client):
        resp = client.get("/api/configuracion")
        data = resp.json()
        assert "abc123" not in str(data)
        assert data["telegram"]["has_bot_token"] is True


# ── POST /api/configuracion ──────────────────────────────────────────────────

class TestApiSaveConfiguracion:
    """POST /api/configuracion persists changes and handles secrets correctly."""

    @pytest.fixture
    def config_path(self, tmp_path, monkeypatch):
        import src.api as api_module
        from src.crypto import encrypt_value
        from src.auth import hash_password

        existing = {
            "librelinkup": {
                "email": "old@example.com",
                "password": encrypt_value("oldpassword"),
                "region": "EU",
            },
            "dashboard_auth": {
                "username": "admin",
                "password_hash": hash_password("adminpass"),
            },
            "alerts": {
                "low_threshold": 70,
                "high_threshold": 180,
                "cooldown_minutes": 20,
                "max_reading_age_minutes": 15,
                "messages": {
                    "low": "LOW {patient_name} {value} {trend}",
                    "high": "HIGH {patient_name} {value} {trend}",
                },
                "trend": {"enabled": True},
            },
            "outputs": [
                {
                    "type": "telegram",
                    "enabled": True,
                    "bot_token": "oldtoken",
                    "chat_id": "999",
                }
            ],
            "monitoring": {"mode": "cron", "interval_seconds": 300},
            "dashboard": {"enabled": True, "host": "0.0.0.0", "port": 8080},
        }
        monkeypatch.setattr(api_module, "_config", existing)
        cfg_file = tmp_path / "config.yaml"
        import yaml
        cfg_file.write_text(yaml.safe_dump(existing))
        monkeypatch.setattr(api_module, "PROJECT_ROOT", tmp_path)
        return cfg_file

    def test_save_returns_success(self, client, config_path):
        resp = client.post("/api/configuracion", json={
            "librelinkup_email": "new@example.com",
            "librelinkup_region": "US",
            "low_threshold": 80,
            "high_threshold": 200,
            "cooldown_minutes": 25,
            "max_reading_age_minutes": 10,
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_saves_to_disk(self, client, config_path):
        client.post("/api/configuracion", json={
            "librelinkup_email": "saved@example.com",
            "librelinkup_region": "US",
            "low_threshold": 80,
            "high_threshold": 200,
            "cooldown_minutes": 25,
            "max_reading_age_minutes": 10,
        })
        import yaml
        saved = yaml.safe_load(config_path.read_text())
        assert saved["librelinkup"]["email"] == "saved@example.com"

    def test_empty_password_does_not_overwrite_secret(self, client, config_path):
        """Sending empty password must preserve the existing encrypted password."""
        import src.api as api_module
        from src.crypto import encrypt_value

        original_encrypted = encrypt_value("oldpassword")
        import src.api as api_module
        api_module._config["librelinkup"]["password"] = original_encrypted

        client.post("/api/configuracion", json={
            "librelinkup_email": "test@example.com",
            "librelinkup_password": "",  # empty → keep existing
            "librelinkup_region": "EU",
            "low_threshold": 70,
            "high_threshold": 180,
            "cooldown_minutes": 20,
            "max_reading_age_minutes": 15,
        })

        import yaml
        saved = yaml.safe_load(config_path.read_text())
        # The saved password must NOT be empty
        assert saved["librelinkup"]["password"], "Password was cleared unexpectedly"
        # The saved password must still be encrypted
        from src.crypto import is_encrypted, decrypt_value
        assert is_encrypted(saved["librelinkup"]["password"])
        assert decrypt_value(saved["librelinkup"]["password"]) == "oldpassword"

    def test_empty_bot_token_preserves_existing(self, client, config_path):
        """Sending empty bot_token must preserve the existing Telegram token."""
        client.post("/api/configuracion", json={
            "librelinkup_email": "test@example.com",
            "librelinkup_region": "EU",
            "low_threshold": 70,
            "high_threshold": 180,
            "cooldown_minutes": 20,
            "max_reading_age_minutes": 10,
            "telegram_enabled": True,
            "telegram_bot_token": "",  # empty → keep existing
            "telegram_chat_id": "999",
        })

        import yaml
        saved = yaml.safe_load(config_path.read_text())
        tg = next((o for o in saved.get("outputs", []) if o.get("type") == "telegram"), {})
        assert tg.get("bot_token") == "oldtoken"

    def test_invalid_thresholds_rejected(self, client, config_path):
        resp = client.post("/api/configuracion", json={
            "low_threshold": 200,
            "high_threshold": 100,  # low >= high → error
        })
        assert resp.status_code == 422

    def test_invalid_region_rejected(self, client, config_path):
        resp = client.post("/api/configuracion", json={
            "librelinkup_region": "INVALID",
        })
        assert resp.status_code == 422

    def test_telegram_enabled_without_token_rejected(self, client, config_path):
        import src.api as api_module
        # Remove bot_token from config so empty field has nothing to fall back on
        api_module._config["outputs"] = [
            {"type": "telegram", "enabled": False, "bot_token": "", "chat_id": ""}
        ]
        resp = client.post("/api/configuracion", json={
            "librelinkup_email": "test@example.com",
            "librelinkup_region": "EU",
            "low_threshold": 70,
            "high_threshold": 180,
            "cooldown_minutes": 20,
            "max_reading_age_minutes": 15,
            "telegram_enabled": True,
            "telegram_bot_token": "",  # no token → should fail
            "telegram_chat_id": "123",
        })
        assert resp.status_code == 422

    def test_no_config_returns_409(self, client, monkeypatch):
        import src.api as api_module
        monkeypatch.setattr(api_module, "_config", {})
        resp = client.post("/api/configuracion", json={"low_threshold": 70})
        assert resp.status_code == 409


# ── POST /api/configuracion/probar-librelinkup ────────────────────────────────

class TestApiProbarLibreLinkUp:
    """Test LibreLinkUp connection endpoint."""

    @pytest.fixture(autouse=True)
    def with_ll_config(self, monkeypatch):
        import src.api as api_module
        from src.crypto import encrypt_value
        monkeypatch.setattr(api_module, "_config", {
            "librelinkup": {
                "email": "saved@example.com",
                "password": encrypt_value("savedpassword"),
                "region": "EU",
            },
            "outputs": [],
        })

    def test_success_result(self, client, monkeypatch):
        monkeypatch.setattr(
            "src.api._test_librelinkup",
            lambda email, password, region: {
                "ok": True,
                "message": "Conexión exitosa con LibreLinkUp.",
                "patients": [{"name": "Ana García", "value": 110, "status": "NORMAL"}],
            },
        )
        resp = client.post("/api/configuracion/probar-librelinkup", json={
            "email": "test@example.com",
            "password": "pass",
            "region": "EU",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "LibreLinkUp" in data["message"]

    def test_failure_result(self, client, monkeypatch):
        monkeypatch.setattr(
            "src.api._test_librelinkup",
            lambda email, password, region: {
                "ok": False,
                "message": "Credenciales inválidas. Verifica email y contraseña.",
                "patients": [],
            },
        )
        resp = client.post("/api/configuracion/probar-librelinkup", json={
            "email": "bad@example.com",
            "password": "wrongpass",
            "region": "EU",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert "inválidas" in data["message"] or "LibreLinkUp" in data["message"]

    def test_uses_saved_password_when_empty(self, client, monkeypatch):
        """When password field is empty, the saved (decrypted) password is used."""
        called_with = {}

        def fake_test(email, password, region):
            called_with["password"] = password
            return {"ok": True, "message": "ok", "patients": []}

        monkeypatch.setattr("src.api._test_librelinkup", fake_test)
        client.post("/api/configuracion/probar-librelinkup", json={
            "email": "test@example.com",
            "password": "",  # empty → use saved
            "region": "EU",
        })
        assert called_with.get("password") == "savedpassword"

    def test_missing_email_returns_422(self, client, monkeypatch):
        import src.api as api_module
        monkeypatch.setattr(api_module, "_config", {"librelinkup": {}, "outputs": []})
        resp = client.post("/api/configuracion/probar-librelinkup", json={
            "email": "",
            "password": "",
            "region": "EU",
        })
        assert resp.status_code == 422


# ── POST /api/configuracion/probar-telegram ──────────────────────────────────

class TestApiProbarTelegram:
    """Test Telegram endpoint."""

    @pytest.fixture(autouse=True)
    def with_tg_config(self, monkeypatch):
        import src.api as api_module
        monkeypatch.setattr(api_module, "_config", {
            "librelinkup": {},
            "outputs": [
                {
                    "type": "telegram",
                    "enabled": True,
                    "bot_token": "savedtoken",
                    "chat_id": "savedchat",
                }
            ],
        })

    def test_success_result(self, client, monkeypatch):
        monkeypatch.setattr(
            "src.api._test_telegram",
            lambda bot_token, chat_id: {
                "ok": True,
                "message": "Telegram configurado correctamente.",
            },
        )
        resp = client.post("/api/configuracion/probar-telegram", json={
            "bot_token": "mytoken",
            "chat_id": "123456",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

    def test_failure_result(self, client, monkeypatch):
        monkeypatch.setattr(
            "src.api._test_telegram",
            lambda bot_token, chat_id: {
                "ok": False,
                "message": "Token de bot inválido.",
            },
        )
        resp = client.post("/api/configuracion/probar-telegram", json={
            "bot_token": "badtoken",
            "chat_id": "123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False

    def test_uses_saved_token_when_empty(self, client, monkeypatch):
        """When bot_token is empty, the saved token is used."""
        called_with = {}

        def fake_test(bot_token, chat_id):
            called_with["bot_token"] = bot_token
            return {"ok": True, "message": "ok"}

        monkeypatch.setattr("src.api._test_telegram", fake_test)
        client.post("/api/configuracion/probar-telegram", json={
            "bot_token": "",  # empty → use saved
            "chat_id": "savedchat",
        })
        assert called_with.get("bot_token") == "savedtoken"

    def test_missing_token_and_chat_returns_422(self, client, monkeypatch):
        import src.api as api_module
        monkeypatch.setattr(api_module, "_config", {"librelinkup": {}, "outputs": []})
        resp = client.post("/api/configuracion/probar-telegram", json={
            "bot_token": "",
            "chat_id": "",
        })
        assert resp.status_code == 422


# ── Setup route still works ──────────────────────────────────────────────────

class TestSetupRouteUnchanged:
    """The /setup route must remain accessible after adding /configuracion."""

    def test_setup_page_returns_200(self, client):
        resp = client.get("/setup")
        assert resp.status_code == 200

    def test_setup_page_has_wizard_content(self, client):
        resp = client.get("/setup")
        assert "text/html" in resp.headers["content-type"]

    def test_login_page_returns_200(self, client, monkeypatch):
        monkeypatch.setattr("src.api.is_configured", lambda: True)
        resp = client.get("/login")
        assert resp.status_code == 200
