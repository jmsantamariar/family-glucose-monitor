"""Tests for src.analytics.glycemic_metrics.compute_metrics()."""
import pytest

from src.analytics.glycemic_metrics import compute_metrics


def _readings(values):
    """Build a list of reading dicts from raw glucose values."""
    return [{"glucose_value": v, "timestamp": f"t{i}"} for i, v in enumerate(values)]


# ── Result shape ─────────────────────────────────────────────────────────────


class TestResultShape:

    def test_all_expected_keys_present(self):
        result = compute_metrics(_readings([100, 110, 120]))
        expected_keys = {
            "n_readings",
            "mean", "median", "stdev", "min", "max",
            "tir_severe_low_pct", "tir_low_pct", "tir_in_range_pct",
            "tir_high_pct", "tir_severe_high_pct",
            "gmi", "cv_pct", "mage",
        }
        assert set(result.keys()) == expected_keys

    def test_n_readings_matches_input_length(self):
        result = compute_metrics(_readings([100, 110, 120, 130]))
        assert result["n_readings"] == 4


# ── Empty input ──────────────────────────────────────────────────────────────


class TestEmptyInput:

    def test_empty_list_returns_n_zero(self):
        result = compute_metrics([])
        assert result["n_readings"] == 0

    def test_empty_list_returns_none_for_descriptive_stats(self):
        result = compute_metrics([])
        for key in ("mean", "median", "stdev", "min", "max", "gmi", "cv_pct", "mage"):
            assert result[key] is None, f"{key} should be None on empty input"

    def test_empty_list_returns_zero_for_tir_buckets(self):
        result = compute_metrics([])
        for key in (
            "tir_severe_low_pct", "tir_low_pct", "tir_in_range_pct",
            "tir_high_pct", "tir_severe_high_pct",
        ):
            assert result[key] == 0.0


# ── Descriptive stats ────────────────────────────────────────────────────────


class TestDescriptiveStats:

    def test_mean_of_known_values(self):
        # mean(100, 200) = 150
        result = compute_metrics(_readings([100, 200]))
        assert result["mean"] == 150.0

    def test_median_of_odd_count(self):
        result = compute_metrics(_readings([100, 120, 140]))
        assert result["median"] == 120.0

    def test_min_and_max(self):
        result = compute_metrics(_readings([100, 130, 90, 200, 80]))
        assert result["min"] == 80
        assert result["max"] == 200

    def test_stdev_zero_when_all_identical(self):
        result = compute_metrics(_readings([120, 120, 120, 120]))
        assert result["stdev"] == 0.0

    def test_single_reading_stdev_is_zero(self):
        """One sample → no spread; we use pstdev which would error → coerce 0."""
        result = compute_metrics(_readings([120]))
        assert result["stdev"] == 0.0


# ── TIR buckets ──────────────────────────────────────────────────────────────


class TestTIR:

    def test_all_in_range(self):
        result = compute_metrics(_readings([80, 100, 120, 150, 180]))
        assert result["tir_in_range_pct"] == 100.0
        assert result["tir_low_pct"] == 0.0
        assert result["tir_high_pct"] == 0.0

    def test_severe_low_bucket(self):
        # 53 < 54 → severe low
        result = compute_metrics(_readings([53, 100, 100, 100]))
        assert result["tir_severe_low_pct"] == 25.0

    def test_low_bucket(self):
        # 60 is between 54 and 70
        result = compute_metrics(_readings([60, 100, 100, 100]))
        assert result["tir_low_pct"] == 25.0
        assert result["tir_severe_low_pct"] == 0.0

    def test_high_bucket(self):
        # 200 is between 180 and 250
        result = compute_metrics(_readings([100, 200, 200, 200]))
        assert result["tir_high_pct"] == 75.0

    def test_severe_high_bucket(self):
        # 260 > 250 → severe high
        result = compute_metrics(_readings([100, 260, 260, 260]))
        assert result["tir_severe_high_pct"] == 75.0

    def test_boundaries_70_and_180_are_in_range(self):
        # Per consensus: 70-180 inclusive
        result = compute_metrics(_readings([70, 180]))
        assert result["tir_in_range_pct"] == 100.0

    def test_buckets_sum_to_100(self):
        """TIR buckets always sum to ~100% (modulo rounding) by construction."""
        result = compute_metrics(_readings([50, 65, 80, 100, 150, 200, 260]))
        total = (
            result["tir_severe_low_pct"]
            + result["tir_low_pct"]
            + result["tir_in_range_pct"]
            + result["tir_high_pct"]
            + result["tir_severe_high_pct"]
        )
        assert abs(total - 100.0) < 0.5  # tolerance for rounding


# ── GMI ──────────────────────────────────────────────────────────────────────


class TestGMI:

    def test_gmi_formula_at_120(self):
        # GMI = 3.31 + 0.02392 * 120 = 6.18
        result = compute_metrics(_readings([120]))
        assert result["gmi"] == 6.18

    def test_gmi_formula_at_150(self):
        # GMI = 3.31 + 0.02392 * 150 = 6.898 → 6.9
        result = compute_metrics(_readings([150]))
        assert result["gmi"] == 6.9

    def test_gmi_increases_with_mean(self):
        low = compute_metrics(_readings([100]))["gmi"]
        high = compute_metrics(_readings([200]))["gmi"]
        assert high > low


# ── CV ───────────────────────────────────────────────────────────────────────


class TestCV:

    def test_cv_zero_when_no_variability(self):
        result = compute_metrics(_readings([120, 120, 120]))
        assert result["cv_pct"] == 0.0

    def test_cv_formula(self):
        # values [100, 200] → mean 150, pstdev 50 → CV = 50/150*100 = 33.3
        result = compute_metrics(_readings([100, 200]))
        assert result["cv_pct"] == pytest.approx(33.3, abs=0.1)


# ── MAGE ─────────────────────────────────────────────────────────────────────


class TestMAGE:

    def test_mage_none_for_under_3_readings(self):
        assert compute_metrics(_readings([100]))["mage"] is None
        assert compute_metrics(_readings([100, 200]))["mage"] is None

    def test_mage_none_when_flat_trace(self):
        """All identical values → SD=0 → MAGE None (no excursions)."""
        result = compute_metrics(_readings([120] * 10))
        assert result["mage"] is None

    def test_mage_detects_alternating_excursions(self):
        """A clear zig-zag with amplitudes > 1 SD must produce a non-None MAGE."""
        # 100 → 200 → 100 → 200 → 100: amplitudes are all 100, SD ~50
        result = compute_metrics(_readings([100, 200, 100, 200, 100, 200, 100]))
        assert result["mage"] is not None
        assert result["mage"] > 0


# ── Integration: ignored fields ──────────────────────────────────────────────


class TestRobustnessToExtraFields:

    def test_ignores_unrelated_fields(self):
        """Extra fields in input dicts are silently ignored."""
        readings = [
            {"glucose_value": 100, "timestamp": "t0", "patient_id": "p1", "patient_name": "Ana"},
            {"glucose_value": 150, "timestamp": "t1", "patient_id": "p1", "patient_name": "Ana"},
        ]
        result = compute_metrics(readings)
        assert result["mean"] == 125.0

    def test_skips_dicts_without_glucose_value(self):
        """Defensive: malformed entries without glucose_value don't crash."""
        readings = [
            {"glucose_value": 100, "timestamp": "t0"},
            {"timestamp": "t1"},  # missing glucose_value
            {"glucose_value": 150, "timestamp": "t2"},
        ]
        result = compute_metrics(readings)
        assert result["n_readings"] == 2
        assert result["mean"] == 125.0
