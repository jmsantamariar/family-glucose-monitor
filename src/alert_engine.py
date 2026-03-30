"""Alert logic: threshold evaluation, cooldown, stale detection, message building with patient name."""
from datetime import datetime, timezone


def evaluate(glucose_value: int, config: dict) -> str:
    low = config["alerts"]["low_threshold"]
    high = config["alerts"]["high_threshold"]
    if glucose_value < low:
        return "low"
    if glucose_value > high:
        return "high"
    return "normal"


def is_stale(reading_timestamp: datetime, max_age_minutes: int) -> bool:
    now = datetime.now(timezone.utc)
    age = now - reading_timestamp
    return age.total_seconds() > max_age_minutes * 60


def should_alert(level: str, state: dict, cooldown_minutes: int) -> bool:
    if level == "normal":
        return False
    last_time = state.get("last_alert_time")
    last_level = state.get("last_alert_level")
    if not last_time:
        return True
    if level != last_level:
        return True
    last_dt = datetime.fromisoformat(last_time)
    now = datetime.now(timezone.utc)
    elapsed = (now - last_dt).total_seconds()
    return elapsed > cooldown_minutes * 60


def build_message(glucose_value: int, level: str, trend_arrow: str,
                  patient_name: str, config: dict | None = None) -> str:
    messages = {}
    if config:
        messages = config.get("alerts", {}).get("messages", {})
    template = messages.get(level, "")
    if not template:
        defaults = {
            "low": "⚠️ {patient_name}: glucosa en {value} mg/dL {trend} — BAJA",
            "high": "⚠️ {patient_name}: glucosa en {value} mg/dL {trend} — ALTA",
        }
        template = defaults.get(
            level, "Alerta: {patient_name} glucosa {value} mg/dL {trend}, nivel {level}"
        )
    return template.format(
        value=glucose_value, trend=trend_arrow, level=level, patient_name=patient_name
    )
