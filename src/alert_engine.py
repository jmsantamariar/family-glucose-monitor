"""Alert logic: threshold evaluation, cooldown, stale detection, message building."""
from datetime import datetime, timezone


def evaluate(glucose_value: int, config: dict) -> str:
    """Return 'low', 'high', or 'normal' based on configured thresholds."""
    low = config["alerts"]["low_threshold"]
    high = config["alerts"]["high_threshold"]
    if glucose_value < low:
        return "low"
    if glucose_value > high:
        return "high"
    return "normal"


def is_stale(reading_timestamp: datetime, max_age_minutes: int) -> bool:
    """Return True if the reading is older than max_age_minutes."""
    now = datetime.now(timezone.utc)
    age = now - reading_timestamp
    return age.total_seconds() > max_age_minutes * 60


def should_alert(level: str, state: dict, cooldown_minutes: int) -> bool:
    """Return True if an alert should be sent based on level, state, and cooldown."""
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
                  patient_name: str = "", config: dict | None = None) -> str:
    """Build alert message using configurable templates from config."""
    messages = {}
    if config:
        messages = config.get("alerts", {}).get("messages", {})
    template = messages.get(level, "")
    if not template:
        defaults = {
            "low": "⚠️ {patient_name}: glucosa en {value} mg/dL {trend} — BAJA",
            "high": "⚠️ {patient_name}: glucosa en {value} mg/dL {trend} — ALTA",
        }
        template = defaults.get(level, "Alert: {patient_name} glucose {value} mg/dL {trend}, level {level}")
    return template.format(value=glucose_value, trend=trend_arrow, level=level, patient_name=patient_name)
