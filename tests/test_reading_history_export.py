"""Tests for GET /api/patients/{patient_id}/history/export.

Covers:
- CSV format: BOM, headers, row content, content-type, content-disposition.
- JSON format: envelope shape, metadata, content-type, content-disposition.
- Validation: days clamp [1, 365], format whitelist (csv|json), default values.
- Auth/404: unknown patient returns 404 (auth itself handled by middleware).
"""
import json
import pytest
from fastapi.testclient import TestClient

# Re-use the fixtures and helpers from the main api test suite so this file
# stays in lock-step with the rest of the api tests.
from tests.test_api import (
    tmp_cache,  # noqa: F401 — pytest fixture re-export
    client,     # noqa: F401
    _write_readings,
)


# ── Local fixture: temporary reading_history.db ──────────────────────────────


@pytest.fixture
def rh_db(tmp_path, monkeypatch):
    """Provide a temporary reading_history.db pointed at by env var."""
    import src.reading_history as rh
    db_file = tmp_path / "reading_history.db"
    rh.init_db(str(db_file))
    rh._engines.pop(str(db_file), None)
    rh.init_db(str(db_file))
    monkeypatch.setenv("READING_HISTORY_DB", str(db_file))
    return db_file


# ── Shared setup: a known patient in the cache + a known reading on disk ─────


def _seed_one_patient_with_one_reading(tmp_cache, rh_db):
    """Populate the in-memory cache so the endpoint passes the 404 gate, and
    log one glucose reading so the body is non-empty."""
    import src.reading_history as rh
    _write_readings(tmp_cache, [
        {"patient_id": "p1", "patient_name": "Ana", "value": 120, "trend_arrow": "→"},
    ])
    rh.log_reading(str(rh_db), "p1", "Ana", 120)


# ── CSV format ───────────────────────────────────────────────────────────────


class TestExportCsv:

    def test_csv_returns_200(self, client, tmp_cache, rh_db):
        _seed_one_patient_with_one_reading(tmp_cache, rh_db)
        resp = client.get("/api/patients/p1/history/export?format=csv&days=1")
        assert resp.status_code == 200

    def test_csv_default_format_is_csv(self, client, tmp_cache, rh_db):
        _seed_one_patient_with_one_reading(tmp_cache, rh_db)
        resp = client.get("/api/patients/p1/history/export?days=1")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/csv")

    def test_csv_has_utf8_bom(self, client, tmp_cache, rh_db):
        _seed_one_patient_with_one_reading(tmp_cache, rh_db)
        resp = client.get("/api/patients/p1/history/export?format=csv&days=1")
        # The BOM is the first character of the response body
        assert resp.content[:3] == b"\xef\xbb\xbf", \
            f"expected UTF-8 BOM, got {resp.content[:6]!r}"

    def test_csv_has_header_row(self, client, tmp_cache, rh_db):
        _seed_one_patient_with_one_reading(tmp_cache, rh_db)
        resp = client.get("/api/patients/p1/history/export?format=csv&days=1")
        text = resp.text
        # Skip BOM to read first line
        first_line = text.lstrip("﻿").splitlines()[0]
        assert first_line == "timestamp,patient_id,patient_name,glucose_value"

    def test_csv_contains_logged_reading(self, client, tmp_cache, rh_db):
        _seed_one_patient_with_one_reading(tmp_cache, rh_db)
        resp = client.get("/api/patients/p1/history/export?format=csv&days=1")
        assert "p1,Ana,120" in resp.text

    def test_csv_content_disposition_is_attachment(self, client, tmp_cache, rh_db):
        _seed_one_patient_with_one_reading(tmp_cache, rh_db)
        resp = client.get("/api/patients/p1/history/export?format=csv&days=1")
        cd = resp.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert ".csv" in cd
        assert "p1" in cd

    def test_csv_empty_history_still_returns_header(self, client, tmp_cache, rh_db):
        # Patient exists in cache but has no history logged yet
        _write_readings(tmp_cache, [
            {"patient_id": "p1", "patient_name": "Ana", "value": 120, "trend_arrow": "→"},
        ])
        resp = client.get("/api/patients/p1/history/export?format=csv&days=1")
        assert resp.status_code == 200
        first_line = resp.text.lstrip("﻿").splitlines()[0]
        assert first_line == "timestamp,patient_id,patient_name,glucose_value"


# ── JSON format ──────────────────────────────────────────────────────────────


class TestExportJson:

    def test_json_returns_200(self, client, tmp_cache, rh_db):
        _seed_one_patient_with_one_reading(tmp_cache, rh_db)
        resp = client.get("/api/patients/p1/history/export?format=json&days=1")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/json")

    def test_json_envelope_has_metadata(self, client, tmp_cache, rh_db):
        _seed_one_patient_with_one_reading(tmp_cache, rh_db)
        resp = client.get("/api/patients/p1/history/export?format=json&days=7")
        body = resp.json()
        assert body["patient_id"] == "p1"
        assert body["patient_name"] == "Ana"
        assert body["period_days"] == 7
        assert isinstance(body["count"], int)
        assert "generated_at" in body
        assert isinstance(body["readings"], list)

    def test_json_count_matches_readings_length(self, client, tmp_cache, rh_db):
        """count must always equal len(readings) — invariant of the envelope."""
        import src.reading_history as rh
        _write_readings(tmp_cache, [
            {"patient_id": "p1", "patient_name": "Ana", "value": 120, "trend_arrow": "→"},
        ])
        rh.log_reading(str(rh_db), "p1", "Ana", 110)
        rh.log_reading(str(rh_db), "p1", "Ana", 125)
        rh.log_reading(str(rh_db), "p1", "Ana", 130)
        resp = client.get("/api/patients/p1/history/export?format=json&days=1")
        body = resp.json()
        # NOTE: the in-memory cache load also auto-logs the latest reading
        # (api.py line ~395). We don't assert exact count for that reason —
        # only the invariant that the envelope's count field is self-consistent.
        assert body["count"] == len(body["readings"])
        assert body["count"] >= 3  # at minimum the three we explicitly logged

    def test_json_content_disposition_is_attachment(self, client, tmp_cache, rh_db):
        _seed_one_patient_with_one_reading(tmp_cache, rh_db)
        resp = client.get("/api/patients/p1/history/export?format=json&days=1")
        cd = resp.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert ".json" in cd

    def test_json_count_invariant_when_no_explicit_logs(self, client, tmp_cache, rh_db):
        """Even with no explicit log_reading() calls, the envelope must satisfy
        count == len(readings) (the cache loader may auto-log, but the
        invariant must always hold)."""
        _write_readings(tmp_cache, [
            {"patient_id": "p1", "patient_name": "Ana", "value": 120, "trend_arrow": "→"},
        ])
        resp = client.get("/api/patients/p1/history/export?format=json&days=1")
        body = resp.json()
        assert body["count"] == len(body["readings"])


# ── Validation ──────────────────────────────────────────────────────────────


class TestExportValidation:

    def test_days_zero_is_422(self, client, tmp_cache, rh_db):
        _seed_one_patient_with_one_reading(tmp_cache, rh_db)
        resp = client.get("/api/patients/p1/history/export?days=0")
        assert resp.status_code == 422

    def test_days_above_365_is_422(self, client, tmp_cache, rh_db):
        _seed_one_patient_with_one_reading(tmp_cache, rh_db)
        resp = client.get("/api/patients/p1/history/export?days=366")
        assert resp.status_code == 422

    def test_invalid_format_is_422(self, client, tmp_cache, rh_db):
        _seed_one_patient_with_one_reading(tmp_cache, rh_db)
        resp = client.get("/api/patients/p1/history/export?format=xml")
        assert resp.status_code == 422

    def test_default_days_is_7(self, client, tmp_cache, rh_db):
        _seed_one_patient_with_one_reading(tmp_cache, rh_db)
        resp = client.get("/api/patients/p1/history/export?format=json")
        assert resp.status_code == 200
        assert resp.json()["period_days"] == 7

    def test_days_max_365_accepted(self, client, tmp_cache, rh_db):
        _seed_one_patient_with_one_reading(tmp_cache, rh_db)
        resp = client.get("/api/patients/p1/history/export?format=json&days=365")
        assert resp.status_code == 200
        assert resp.json()["period_days"] == 365

    def test_unknown_patient_returns_404(self, client, tmp_cache, rh_db):
        # Cache empty → no patient → 404
        resp = client.get("/api/patients/nobody/history/export?days=1")
        assert resp.status_code == 404
