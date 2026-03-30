"""Alert logic: threshold evaluation, cooldown, stale detection, message building with patient name."""
from datetime import datetime, timezone

# Trend arrow classification
TREND_ARROWS = {
    "↑": "rising_fast",
    "↗": "rising",
    "→": "stable",
    "↘": "falling",
    "↓": "falling_fast",
    # Also support text names from pylibrelinkup
    "SingleUp": "rising_fast",
    "FortyFiveUp": "rising",
    "Flat": "stable",
    "FortyFiveDown": "falling",
    "SingleDown": "falling_fast",
}


def classify_trend(trend_arrow: str) -> str:
    """Classify a trend arrow into a trend category."""
    return TREND_ARROWS.get(trend_arrow, "unknown")


def evaluate(glucose_value: int, config: dict) -> str:
    low = config["alerts"]["low_threshold"]
    high = config["alerts"]["high_threshold"]
    if glucose_value < low:
        return "low"
    if glucose_value > high:
        return "high"
    return "normal"


def evaluate_trend(glucose_value: int, trend_arrow: str, config: dict) -> str:
    """
    Evaluate if a trend is dangerous based on glucose value + direction.

    Returns: 'falling_fast', 'falling', 'rising_fast', 'rising', or 'normal'

    Logic:
    - Any glucose AND falling_fast → alert (rapid drop is always dangerous)
    - glucose < low_approaching_threshold AND falling → alert (approaching hypo)
    - glucose > high_approaching_threshold AND rising/rising_fast → alert (approaching hyper)
    - Otherwise → normal
    """
    trend = classify_trend(trend_arrow)

    trend_config = config.get("alerts", {}).get("trend", {})
    if not trend_config.get("enabled", False):
        return "normal"

    low_warn = trend_config.get("low_approaching_threshold", 100)
    high_warn = trend_config.get("high_approaching_threshold", 150)

    # Falling fast is ALWAYS dangerous regardless of current value
    if trend == "falling_fast":
        return "falling_fast"

    # Approaching hypoglycemia
    if glucose_value < low_warn and trend == "falling":
        return "falling"

    # Approaching hyperglycemia
    if glucose_value > high_warn and trend in ("rising", "rising_fast"):
        if trend == "rising_fast":
            return "rising_fast"
        return "rising"

    return "normal"


def is_stale(reading_timestamp: datetime, max_age_minutes: int) -> bool:
    now = datetime.now(timezone.utc)
    age = now - reading_timestamp
    return age.total_seconds() > max_age_minutes * 60


def should_alert(level: str, state: dict, cooldown_minutes: int, trend_alert: str = "normal") -> bool:
    """
    Return True if an alert should be sent based on level, trend, state, and cooldown.
    Triggers on dangerous trends even when glucose is in normal range.
    """
    # Determine effective alert type
    effective_alert = level if level != "normal" else None

    if not effective_alert and trend_alert != "normal":
        effective_alert = f"trend_{trend_alert}"

    if not effective_alert:
        return False  # glucose normal AND trend normal

    last_time = state.get("last_alert_time")
    last_level = state.get("last_alert_level")

    if not last_time:
        return True

    if effective_alert != last_level:
        return True

    last_dt = datetime.fromisoformat(last_time)
    now = datetime.now(timezone.utc)
    elapsed = (now - last_dt).total_seconds()
    return elapsed > cooldown_minutes * 60


def build_message(glucose_value: int, level: str, trend_arrow: str,
                  patient_name: str, config: dict | None = None,
                  trend_alert: str = "normal") -> str:
    """
    Build alert message. Includes trend context when level is normal but trend is dangerous.
    """
    messages = {}
    if config:
        messages = config.get("alerts", {}).get("messages", {})

    if level != "normal":
        template = messages.get(level, "")
        if not template:
            defaults = {
                "low": "⚠️ {patient_name}: glucosa en {value} mg/dL {trend} — BAJA",
                "high": "⚠️ {patient_name}: glucosa en {value} mg/dL {trend} — ALTA",
            }
            template = defaults.get(
                level, "Alerta: {patient_name} glucosa {value} mg/dL {trend}, nivel {level}"
            )
    else:
        # Trend-based alert
        trend_messages = messages.get("trend", {})
        template = trend_messages.get(trend_alert, "")
        if not template:
            trend_defaults = {
                "falling_fast": "🔻 {patient_name}: glucosa en {value} mg/dL {trend} — BAJANDO RÁPIDO",
                "falling": "📉 {patient_name}: glucosa en {value} mg/dL {trend} — bajando, posible hipo",
                "rising_fast": "🔺 {patient_name}: glucosa en {value} mg/dL {trend} — SUBIENDO RÁPIDO",
                "rising": "📈 {patient_name}: glucosa en {value} mg/dL {trend} — subiendo, posible hiper",
            }
            template = trend_defaults.get(
                trend_alert,
                "Alerta: {patient_name} glucosa {value} mg/dL {trend}, nivel {level}",
            )

    return template.format(
        value=glucose_value, trend=trend_arrow, level=level,
        patient_name=patient_name, trend_alert=trend_alert
    )
