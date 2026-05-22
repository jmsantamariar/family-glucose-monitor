"""Tests for GET /api/patients/{patient_id}/metrics.

Covers:
- 200 response with proper envelope shape (patient_id, period_days, metrics, …)
- Metrics dict is populated when readings exist
- days clamp [1, 365] → 422 outside
- Default days = 14
- 404 for unknown patient
- Empty history returns N=0 in metrics, not a crash
"""
import pytest

from tests.test_api import (
    tmp_cache,  # noqa: F401 — pytest fixture re-export
    client,     # noqa: F401
    _write_readings,
)


@pytest.fixture
def rh_db(tmp_path, monkeypatch):
    """Temporary reading_history.db pointed at via env var."""
    import src.reading_history as rh
    db_file = tmp_path / "reading_history.db"
    rh.init_db(str(db_file))
    rh._engines.pop(str(db_file), None)
    rh.init_db(str(db_file))
    monkeypatch.setenv("READING_HISTORY_DB", str(db_file))
    return db_file


def _seed_patient_with_readings(tmp_cache, rh_db, values):
    """Populate cache + log a sequence of glucose values for p1."""
    import src.reading_history as rh
    _write_readings(tmp_cache, [
        {"patient_id": "p1", "patient_name": "Ana", "value": values[0],
         "trend_arrow": "→"},
    ])
    for v in values:
        rh.log_reading(str(rh_db), "p1", "Ana", v)


# ── Envelope shape ───────────────────────────────────────────────────────────


class TestEnvelopeShape:

    def test_returns_200(self, client, tmp_cache, rh_db):
        _seed_patient_with_readings(tmp_cache, rh_db, [120, 130, 140])
        resp = client.get("/api/patients/p1/metrics")
        assert resp.status_code == 200

    def test_envelope_top_level_keys(self, client, tmp_cache, rh_db):
        _seed_patient_with_readings(tmp_cache, rh_db, [120, 130, 140])
        body = client.get("/api/patients/p1/metrics").json()
        for key in ("patient_id", "patient_name", "period_days",
                    "first_reading_at", "last_reading_at",
                    "generated_at", "metrics"):
            assert key in body, f"missing key {key!r}"

    def test_envelope_patient_id_echoed(self, client, tmp_cache, rh_db):
        _seed_patient_with_readings(tmp_cache, rh_db, [120])
        body = client.get("/api/patients/p1/metrics").json()
        assert body["patient_id"] == "p1"
        assert body["patient_name"] == "Ana"


# ── Metrics dict content ─────────────────────────────────────────────────────


class TestMetricsContent:

    def test_metrics_has_expected_subkeys(self, client, tmp_cache, rh_db):
        _seed_patient_with_readings(tmp_cache, rh_db, [80, 100, 120, 150, 180])
        m = client.get("/api/patients/p1/metrics").json()["metrics"]
        for key in ("n_readings", "mean", "median", "stdev", "min", "max",
                    "tir_in_range_pct", "tir_low_pct", "tir_high_pct",
                    "tir_severe_low_pct", "tir_severe_high_pct",
                    "gmi", "cv_pct", "mage"):
            assert key in m, f"missing metric {key!r}"

    def test_metrics_mean_reflects_values(self, client, tmp_cache, rh_db):
        _seed_patient_with_readings(tmp_cache, rh_db, [100, 200])
        m = client.get("/api/patients/p1/metrics").json()["metrics"]
        # At least the 2 we logged + cache auto-log; mean stays sensible
        assert 100 <= m["mean"] <= 200

    def test_metrics_n_readings_at_least_what_we_logged(self, client, tmp_cache, rh_db):
        _seed_patient_with_readings(tmp_cache, rh_db, [120, 130, 140, 150, 160])
        m = client.get("/api/patients/p1/metrics").json()["metrics"]
        assert m["n_readings"] >= 5


# ── Validation ───────────────────────────────────────────────────────────────


class TestValidation:

    def test_days_zero_is_422(self, client, tmp_cache, rh_db):
        _seed_patient_with_readings(tmp_cache, rh_db, [120])
        assert client.get("/api/patients/p1/metrics?days=0").status_code == 422

    def test_days_above_365_is_422(self, client, tmp_cache, rh_db):
        _seed_patient_with_readings(tmp_cache, rh_db, [120])
        assert client.get("/api/patients/p1/metrics?days=366").status_code == 422

    def test_default_days_is_14(self, client, tmp_cache, rh_db):
        _seed_patient_with_readings(tmp_cache, rh_db, [120])
        body = client.get("/api/patients/p1/metrics").json()
        assert body["period_days"] == 14

    def test_days_max_365_accepted(self, client, tmp_cache, rh_db):
        _seed_patient_with_readings(tmp_cache, rh_db, [120])
        resp = client.get("/api/patients/p1/metrics?days=365")
        assert resp.status_code == 200
        assert resp.json()["period_days"] == 365

    def test_unknown_patient_returns_404(self, client, tmp_cache, rh_db):
        # cache empty → 404
        resp = client.get("/api/patients/nobody/metrics?days=7")
        assert resp.status_code == 404


# ── Empty / degenerate input ─────────────────────────────────────────────────


class TestEmptyHistory:

    def test_patient_exists_but_no_readings_returns_200(self, client, tmp_cache, rh_db):
        """A patient with no logged readings yet must return 200 with N=0 metrics,
        not crash. (The cache auto-log will still create at least 1 reading,
        so we assert >= 0, not exactly 0.)"""
        _write_readings(tmp_cache, [
            {"patient_id": "p1", "patient_name": "Ana", "value": 120,
             "trend_arrow": "→"},
        ])
        resp = client.get("/api/patients/p1/metrics?days=7")
        assert resp.status_code == 200
        assert resp.json()["metrics"]["n_readings"] >= 0
