"""Tests for startup checks, bootstrap storage, guardrails, and E2E cache round-trip.

Covers:
* bootstrap_storage: creates missing files, fails on schema mismatch.
* check_config_writable: detects read-only config.yaml.
* ALLOW_INSECURE_LOCAL_API loopback guardrail in api_server.
* acquire_lock() Windows warning (fcntl unavailable in daemon/full mode).
* E2E round-trip: main._save_readings_cache() → api_server reads with custom path.
"""
import importlib
import json
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Sentinel object used by the fcntl-disabling context manager.
_SENTINEL = object()

# ---------------------------------------------------------------------------
# bootstrap_storage
# ---------------------------------------------------------------------------


class TestBootstrapStorage:
    def _make_config(self, tmp_path: Path) -> dict:
        return {
            "state_file": str(tmp_path / "state.json"),
            "alert_history_db": str(tmp_path / "alert_history.db"),
            "api": {"cache_file": str(tmp_path / "readings_cache.json")},
        }

    def test_creates_state_file(self, tmp_path):
        from src.bootstrap import bootstrap_storage

        config = self._make_config(tmp_path)
        bootstrap_storage(config)
        assert (tmp_path / "state.json").exists()

    def test_state_file_is_valid_json(self, tmp_path):
        from src.bootstrap import bootstrap_storage

        config = self._make_config(tmp_path)
        bootstrap_storage(config)
        data = json.loads((tmp_path / "state.json").read_text())
        assert data == {}

    def test_creates_alert_history_db(self, tmp_path):
        from src.bootstrap import bootstrap_storage

        config = self._make_config(tmp_path)
        bootstrap_storage(config)
        assert (tmp_path / "alert_history.db").exists()

    def test_creates_cache_file(self, tmp_path):
        from src.bootstrap import bootstrap_storage

        config = self._make_config(tmp_path)
        bootstrap_storage(config)
        assert (tmp_path / "readings_cache.json").exists()

    def test_cache_file_has_empty_readings(self, tmp_path):
        from src.bootstrap import bootstrap_storage

        config = self._make_config(tmp_path)
        bootstrap_storage(config)
        data = json.loads((tmp_path / "readings_cache.json").read_text())
        assert data["readings"] == []

    def test_idempotent_does_not_overwrite_existing_state(self, tmp_path):
        from src.bootstrap import bootstrap_storage

        config = self._make_config(tmp_path)
        # Pre-existing state
        state_file = tmp_path / "state.json"
        state_file.write_text('{"patient-1": {"last_alert_level": "high"}}')
        bootstrap_storage(config)
        # Must not be overwritten
        assert "patient-1" in json.loads(state_file.read_text())

    def test_schema_mismatch_raises_bootstrap_error(self, tmp_path):
        from src.bootstrap import BootstrapError, bootstrap_storage

        config = self._make_config(tmp_path)
        # Create a DB with a broken schema (missing required columns).
        import sqlite3
        db_path = str(tmp_path / "alert_history.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE alerts (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        with pytest.raises(BootstrapError, match="schema mismatch"):
            bootstrap_storage(config)


# ---------------------------------------------------------------------------
# check_config_writable
# ---------------------------------------------------------------------------


class TestCheckConfigWritable:
    def test_returns_none_when_file_absent_and_dir_writable(self, tmp_path):
        from src.bootstrap import check_config_writable

        result = check_config_writable(tmp_path / "config.yaml")
        assert result is None

    def test_returns_none_when_file_exists_and_writable(self, tmp_path):
        from src.bootstrap import check_config_writable

        cfg = tmp_path / "config.yaml"
        cfg.write_text("key: value")
        result = check_config_writable(cfg)
        assert result is None

    def test_returns_error_when_file_read_only(self, tmp_path):
        from src.bootstrap import check_config_writable
        import os
        import stat as _stat

        cfg = tmp_path / "config.yaml"
        cfg.write_text("key: value")
        # Make read-only
        os.chmod(cfg, _stat.S_IRUSR)
        try:
            result = check_config_writable(cfg)
            assert result is not None
            assert "read-only" in result.lower() or "write" in result.lower()
        finally:
            os.chmod(cfg, _stat.S_IRUSR | _stat.S_IWUSR)


# ---------------------------------------------------------------------------
# ALLOW_INSECURE_LOCAL_API loopback guardrail
# ---------------------------------------------------------------------------


class TestLoopbackGuardrail:
    """The loopback guardrail rejects non-loopback clients when ALLOW_INSECURE_LOCAL_API=1."""

    def _make_client(self, monkeypatch, allow_insecure: bool = True) -> TestClient:
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.setenv("ALLOW_INSECURE_LOCAL_API", "1" if allow_insecure else "0")
        import src.api_server as module
        importlib.reload(module)
        return TestClient(module.app, raise_server_exceptions=False)

    def test_loopback_client_allowed(self, monkeypatch, tmp_path):
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.setenv("ALLOW_INSECURE_LOCAL_API", "1")
        import src.api_server as module
        importlib.reload(module)
        cache_file = tmp_path / "cache.json"
        cache_file.write_text(json.dumps({"readings": [], "updated_at": None}))
        with patch.object(module, "_config", {"api": {"cache_file": str(cache_file)}}):
            # TestClient uses host='testclient'; patch _LOOPBACK_ADDRS to include it
            with patch.object(module, "_LOOPBACK_ADDRS", frozenset({"127.0.0.1", "::1", "testclient"})):
                client = TestClient(module.app)
                response = client.get("/api/health")
        assert response.status_code == 200

    def test_non_loopback_client_rejected_when_insecure(self, monkeypatch, tmp_path):
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.setenv("ALLOW_INSECURE_LOCAL_API", "1")
        import src.api_server as module
        importlib.reload(module)
        cache_file = tmp_path / "cache.json"
        cache_file.write_text(json.dumps({"readings": [], "updated_at": None}))
        with patch.object(module, "_config", {"api": {"cache_file": str(cache_file)}}):
            # Use empty loopback set so 'testclient' is rejected too
            with patch.object(module, "_LOOPBACK_ADDRS", frozenset()):
                client = TestClient(module.app, raise_server_exceptions=False)
                response = client.get("/api/health")
        # Should be rejected with 403
        assert response.status_code == 403

    def test_non_loopback_allowed_when_api_key_set(self, monkeypatch, tmp_path):
        """When API_KEY is configured, the loopback guardrail is not enforced."""
        monkeypatch.setenv("API_KEY", "my-secret-key")
        monkeypatch.setenv("ALLOW_INSECURE_LOCAL_API", "1")
        import src.api_server as module
        importlib.reload(module)
        cache_file = tmp_path / "cache.json"
        cache_file.write_text(json.dumps({"readings": [], "updated_at": None}))
        with patch.object(module, "_config", {"api": {"cache_file": str(cache_file)}}):
            client = TestClient(module.app, raise_server_exceptions=False)
            with patch.object(module, "_LOOPBACK_ADDRS", frozenset()):
                response = client.get(
                    "/api/health",
                    headers={"Authorization": "Bearer my-secret-key"},
                )
        # API_KEY set — loopback guard is bypassed, key check passes
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# acquire_lock Windows warning
# ---------------------------------------------------------------------------


class TestAcquireLockFcntlWarning:
    def _capture_warnings(self, logger_name: str):
        """Return a context manager that directly captures WARNING+ records.

        Handles the case where the named logger has been disabled by
        ``logging.config.fileConfig(disable_existing_loggers=True)`` — which
        Alembic triggers when running migrations in the same test session.
        """
        import logging
        import contextlib

        @contextlib.contextmanager
        def _ctx():
            captured: list[logging.LogRecord] = []

            class _Capture(logging.Handler):
                def emit(self, record: logging.LogRecord) -> None:
                    captured.append(record)

            handler = _Capture(level=logging.WARNING)
            target_logger = logging.getLogger(logger_name)
            old_level = target_logger.level
            old_disabled = target_logger.disabled
            target_logger.addHandler(handler)
            target_logger.disabled = False
            # Ensure the logger itself isn't filtering out WARNING messages.
            if old_level == 0 or old_level > logging.WARNING:
                target_logger.setLevel(logging.WARNING)
            try:
                yield captured
            finally:
                target_logger.removeHandler(handler)
                target_logger.setLevel(old_level)
                target_logger.disabled = old_disabled

        return _ctx()

    def test_daemon_mode_warns_without_fcntl(self, tmp_path):
        """In daemon mode, missing fcntl emits a WARNING-level log message."""
        import src.main as main_mod
        import sys
        from unittest.mock import patch

        lock_path = str(tmp_path / "test.lock")
        with self._capture_warnings("family-glucose-monitor") as records:
            with patch.dict(sys.modules, {"fcntl": None}):
                result = main_mod.acquire_lock(lock_path, mode="daemon")

        assert result is None
        messages = [r.getMessage() for r in records]
        assert any("fcntl" in m for m in messages)
        assert any(r.levelno >= logging.WARNING for r in records if "fcntl" in r.getMessage())

    def test_full_mode_warns_without_fcntl(self, tmp_path):
        """In full mode, missing fcntl emits a WARNING-level log message."""
        import src.main as main_mod
        import sys
        from unittest.mock import patch

        lock_path = str(tmp_path / "test.lock")
        with self._capture_warnings("family-glucose-monitor") as records:
            with patch.dict(sys.modules, {"fcntl": None}):
                result = main_mod.acquire_lock(lock_path, mode="full")

        assert result is None
        assert any("fcntl" in r.getMessage() and r.levelno >= logging.WARNING for r in records)

    def test_cron_mode_does_not_warn_without_fcntl(self, tmp_path):
        """In cron mode, missing fcntl must NOT emit a WARNING."""
        import src.main as main_mod
        import sys
        from unittest.mock import patch

        lock_path = str(tmp_path / "test.lock")
        with self._capture_warnings("family-glucose-monitor") as records:
            with patch.dict(sys.modules, {"fcntl": None}):
                result = main_mod.acquire_lock(lock_path, mode="cron")

        assert result is None
        warning_fcntl = [
            r for r in records
            if "fcntl" in r.getMessage() and r.levelno >= logging.WARNING
        ]
        assert warning_fcntl == [], "cron mode must not warn about missing fcntl"


# ---------------------------------------------------------------------------
# E2E cache round-trip: main writes → api_server reads
# ---------------------------------------------------------------------------


class TestCacheRoundTrip:
    """Integration test: _save_readings_cache writes a cache that api_server can read."""

    SAMPLE_READINGS = [
        {
            "patient_id": "p-001",
            "patient_name": "Test Patient",
            "value": 130,
            "timestamp": "2026-01-01T12:00:00+00:00",
            "trend_name": "Flat",
            "trend_arrow": "→",
            "is_high": False,
            "is_low": False,
        }
    ]

    def test_roundtrip_with_custom_cache_path(self, tmp_path, monkeypatch):
        """_save_readings_cache writes a file that api_server._load_cache reads back."""
        cache_file = tmp_path / "custom_cache.json"
        config = {"api": {"cache_file": str(cache_file)}}

        # 1. Write via main._save_readings_cache
        import src.main as main_mod
        main_mod._save_readings_cache(self.SAMPLE_READINGS, config)

        assert cache_file.exists(), "Cache file must be created by _save_readings_cache"

        # 2. Read via api_server._load_cache with matching config
        import src.api_server as api_server_mod
        monkeypatch.delenv("READINGS_CACHE_FILE", raising=False)
        with patch.object(api_server_mod, "_config", config):
            result = api_server_mod._load_cache()

        assert len(result["readings"]) == 1
        assert result["readings"][0]["patient_id"] == "p-001"
        assert result["readings"][0]["value"] == 130
        assert result["updated_at"] is not None

    def test_roundtrip_via_api_endpoint(self, tmp_path, monkeypatch):
        """After main writes the cache, api_server /api/readings returns the data."""
        cache_file = tmp_path / "custom_cache.json"
        config = {"api": {"cache_file": str(cache_file)}}

        # Write cache
        import src.main as main_mod
        main_mod._save_readings_cache(self.SAMPLE_READINGS, config)

        # Read via HTTP endpoint
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.setenv("ALLOW_INSECURE_LOCAL_API", "1")
        monkeypatch.delenv("READINGS_CACHE_FILE", raising=False)
        import src.api_server as api_server_mod
        importlib.reload(api_server_mod)
        with patch.object(api_server_mod, "_config", config):
            # TestClient uses host='testclient'; include it in allowed loopback addrs.
            with patch.object(api_server_mod, "_LOOPBACK_ADDRS", frozenset({"127.0.0.1", "::1", "testclient"})):
                client = TestClient(api_server_mod.app)
                response = client.get("/api/readings")

        assert response.status_code == 200
        data = response.json()
        assert len(data["readings"]) == 1
        assert data["readings"][0]["patient_id"] == "p-001"

    def test_env_var_cache_path_used_by_both(self, tmp_path, monkeypatch):
        """READINGS_CACHE_FILE env var is respected by both main and api_server."""
        cache_file = tmp_path / "env_cache.json"
        monkeypatch.setenv("READINGS_CACHE_FILE", str(cache_file))
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.setenv("ALLOW_INSECURE_LOCAL_API", "1")

        # Write via main (env var takes precedence over config)
        import src.main as main_mod
        main_mod._save_readings_cache(self.SAMPLE_READINGS, {})

        assert cache_file.exists()

        # Read via api_server with empty config (env var takes precedence)
        import src.api_server as api_server_mod
        importlib.reload(api_server_mod)
        with patch.object(api_server_mod, "_config", {}):
            result = api_server_mod._load_cache()

        assert len(result["readings"]) == 1
        assert result["readings"][0]["patient_id"] == "p-001"
