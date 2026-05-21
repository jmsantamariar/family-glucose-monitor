"""Standard glycemic-control metrics over a list of glucose readings.

The single public entry point is :func:`compute_metrics`, which takes the
shape returned by :func:`src.reading_history.get_readings` and returns a
flat dict suitable for JSON serialization.

Metrics implemented
-------------------
* **mean / median / stdev / min / max** — basic descriptive stats (mg/dL).
* **TIR (Time-in-Range)** family — percentage of readings in five buckets,
  per the 2019 International Consensus on TIR (Battelino et al., *Diabetes
  Care* 42(8): 1593-1603):
    - ``tir_severe_low_pct``     readings  < 54 mg/dL
    - ``tir_low_pct``            readings  54–69 mg/dL
    - ``tir_in_range_pct``       readings  70–180 mg/dL
    - ``tir_high_pct``           readings  181–250 mg/dL
    - ``tir_severe_high_pct``    readings  > 250 mg/dL
  The five buckets always sum to 100% (modulo rounding) by construction.
* **GMI (Glucose Management Indicator)** — estimated HbA1c proxy, formula
  from Bergenstal et al. 2018, *Diabetes Care* 41(11):2275–2280::
        GMI = 3.31 + 0.02392 * mean_glucose_mg_dl
* **CV (Coefficient of Variation)** — variability index, Kovatchev 2006::
        CV = (stdev / mean) * 100
  CV < 36% is considered "stable" by current consensus.
* **MAGE (Mean Amplitude of Glycemic Excursions)** — Service et al. 1970,
  *Diabetes* 19(9):644-655. Identifies local peaks and valleys in the time
  series, computes the absolute amplitude between consecutive turning
  points, filters those exceeding 1 SD, and averages them. Captures
  meal-related and hypo-rebound swings that mean/SD alone miss.

All metrics return ``None`` (not a number) when the input list is empty or
too short to compute the metric meaningfully (e.g. MAGE needs ≥ 3 points).
"""
from __future__ import annotations

import statistics
from typing import Any


# ── Constants used by the TIR buckets ────────────────────────────────────────
_SEVERE_LOW_MAX = 54        # strictly less than this
_LOW_MAX = 70               # strictly less than this (but ≥ 54)
_IN_RANGE_MAX = 180         # inclusive upper bound for "in range"
_HIGH_MAX = 250             # inclusive upper bound for "high" (level 1)
# Anything above _HIGH_MAX is "severe high" (level 2)


def _percent(numerator: int, denominator: int) -> float:
    """Return percentage rounded to one decimal place. Safe on zero denom."""
    if denominator <= 0:
        return 0.0
    return round(100.0 * numerator / denominator, 1)


def _compute_tir(values: list[int]) -> dict[str, float]:
    """Return the five TIR percentages as a flat dict."""
    n = len(values)
    if n == 0:
        return {
            "tir_severe_low_pct": 0.0,
            "tir_low_pct": 0.0,
            "tir_in_range_pct": 0.0,
            "tir_high_pct": 0.0,
            "tir_severe_high_pct": 0.0,
        }
    severe_low = sum(1 for v in values if v < _SEVERE_LOW_MAX)
    low = sum(1 for v in values if _SEVERE_LOW_MAX <= v < _LOW_MAX)
    in_range = sum(1 for v in values if _LOW_MAX <= v <= _IN_RANGE_MAX)
    high = sum(1 for v in values if _IN_RANGE_MAX < v <= _HIGH_MAX)
    severe_high = sum(1 for v in values if v > _HIGH_MAX)
    return {
        "tir_severe_low_pct": _percent(severe_low, n),
        "tir_low_pct": _percent(low, n),
        "tir_in_range_pct": _percent(in_range, n),
        "tir_high_pct": _percent(high, n),
        "tir_severe_high_pct": _percent(severe_high, n),
    }


def _compute_gmi(mean: float) -> float:
    """Bergenstal 2018 — GMI = 3.31 + 0.02392 * mean (mg/dL)."""
    return round(3.31 + 0.02392 * mean, 2)


def _compute_cv(mean: float, stdev: float) -> float:
    """Kovatchev 2006 — CV (%) = stdev / mean * 100."""
    if mean <= 0:
        return 0.0
    return round(stdev / mean * 100.0, 1)


def _compute_mage(values: list[int], stdev: float) -> float | None:
    """Service 1970 — Mean Amplitude of Glycemic Excursions.

    Algorithm:
    1. Find local extrema (peaks and valleys) by simple 3-point comparison.
    2. Compute |amplitude| between each pair of consecutive extrema.
    3. Filter amplitudes that exceed 1 SD of the underlying series.
    4. Return the mean of the qualifying amplitudes.

    Returns ``None`` when fewer than 3 points, when no extrema are found,
    or when no excursion exceeds the SD threshold (a stable trace).
    """
    if len(values) < 3 or stdev <= 0:
        return None

    extrema: list[int] = []
    for i in range(1, len(values) - 1):
        prev_v, curr_v, next_v = values[i - 1], values[i], values[i + 1]
        if curr_v > prev_v and curr_v > next_v:
            extrema.append(curr_v)  # peak
        elif curr_v < prev_v and curr_v < next_v:
            extrema.append(curr_v)  # valley

    if len(extrema) < 2:
        return None

    amplitudes = [abs(extrema[i + 1] - extrema[i]) for i in range(len(extrema) - 1)]
    qualifying = [a for a in amplitudes if a > stdev]
    if not qualifying:
        return None
    return round(sum(qualifying) / len(qualifying), 1)


def compute_metrics(readings: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute the full set of glycemic-control metrics over *readings*.

    Each item in *readings* must have a ``glucose_value`` field (int, mg/dL).
    Other fields (timestamp, patient_id, …) are ignored — order does not matter
    for the descriptive stats, but the caller should pass readings in
    chronological order so that MAGE's peak/valley detection makes sense.

    The result is a flat ``dict`` with the following keys::

        {
            "n_readings": int,
            "mean": float | None,
            "median": float | None,
            "stdev": float | None,
            "min": int | None,
            "max": int | None,
            "tir_severe_low_pct": float,
            "tir_low_pct": float,
            "tir_in_range_pct": float,
            "tir_high_pct": float,
            "tir_severe_high_pct": float,
            "gmi": float | None,
            "cv_pct": float | None,
            "mage": float | None,
        }

    ``None`` indicates the metric could not be computed (typically because
    the input was empty or too short).
    """
    values = [int(r["glucose_value"]) for r in readings if "glucose_value" in r]
    n = len(values)

    result: dict[str, Any] = {
        "n_readings": n,
        "mean": None,
        "median": None,
        "stdev": None,
        "min": None,
        "max": None,
        "gmi": None,
        "cv_pct": None,
        "mage": None,
    }
    result.update(_compute_tir(values))

    if n == 0:
        return result

    mean_val = round(statistics.fmean(values), 1)
    median_val = round(statistics.median(values), 1)
    min_val = min(values)
    max_val = max(values)
    stdev_val = round(statistics.pstdev(values), 1) if n >= 2 else 0.0

    result["mean"] = mean_val
    result["median"] = median_val
    result["min"] = min_val
    result["max"] = max_val
    result["stdev"] = stdev_val
    result["gmi"] = _compute_gmi(mean_val)
    result["cv_pct"] = _compute_cv(mean_val, stdev_val)
    result["mage"] = _compute_mage(values, stdev_val)

    return result
