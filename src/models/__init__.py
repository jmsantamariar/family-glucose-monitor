"""Typed domain models for family-glucose-monitor.

These dataclasses serve as explicit contracts for the data flowing through the
system.  Using typed models rather than bare ``dict`` objects catches attribute
typos at development time, improves IDE autocompletion, and makes the codebase
easier to reason about.

All models use ``dataclasses.dataclass`` so that no extra runtime dependencies
are required beyond the standard library.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class GlucoseReading:
    """A single glucose reading from LibreLinkUp for one patient."""

    patient_id: str
    patient_name: str
    value: int
    timestamp: datetime
    trend_arrow: str

    @classmethod
    def from_dict(cls, data: dict) -> "GlucoseReading":
        """Construct a :class:`GlucoseReading` from the dict returned by glucose_reader."""
        ts = data["timestamp"]
        if not isinstance(ts, datetime):
            ts = datetime.fromisoformat(str(ts))
        return cls(
            patient_id=str(data["patient_id"]),
            patient_name=str(data["patient_name"]),
            value=int(data["value"]),
            timestamp=ts,
            trend_arrow=str(data.get("trend_arrow", "")),
        )

    def to_dict(self) -> dict:
        return {
            "patient_id": self.patient_id,
            "patient_name": self.patient_name,
            "value": self.value,
            "timestamp": self.timestamp,
            "trend_arrow": self.trend_arrow,
        }


@dataclass
class AlertsConfig:
    """Validated alerts section from config.yaml."""

    low_threshold: float
    high_threshold: float
    cooldown_minutes: float
    max_reading_age_minutes: float

    @classmethod
    def from_dict(cls, data: dict) -> "AlertsConfig":
        return cls(
            low_threshold=float(data["low_threshold"]),
            high_threshold=float(data["high_threshold"]),
            cooldown_minutes=float(data["cooldown_minutes"]),
            max_reading_age_minutes=float(data["max_reading_age_minutes"]),
        )


@dataclass
class PatientState:
    """Per-patient alert state persisted in state.json."""

    patient_id: str
    last_alert_time: Optional[str] = None
    last_alert_level: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "last_alert_time": self.last_alert_time,
            "last_alert_level": self.last_alert_level,
        }
