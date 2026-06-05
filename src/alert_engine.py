"""Alert logic: threshold evaluation, cooldown, stale detection, message building with patient name."""
import string as _string
from datetime import datetime, timezone


class _RestrictedFormatter(_string.Formatter):
    """String formatter that blocks attribute/item access in template placeholders.

    Prevents format-string injection: a template like ``{patient_name.__class__}``
    would normally access the ``__class__`` attribute of the substituted value.
    This formatter raises ``KeyError`` for any placeholder that uses ``.`` or
    ``[`` notation so that only simple ``{key}`` substitutions are allowed.
    """

    def get_field(self, field_name: str, args, kwargs):
        if "." in field_name or "[" in field_name:
            raise KeyError(field_name)
        return super().get_field(field_name, args, kwargs)


_formatter = _RestrictedFormatter()

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

    try:
        last_dt = datetime.fromisoformat(last_time)
    except (ValueError, TypeError):
        return True
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
        # Primary schema: alerts.trend.messages (matches config.example.yaml)
        trend_messages = config.get("alerts", {}).get("trend", {}).get("messages", {}) if config else {}
        # Backward compatibility: fall back to alerts.messages.trend if defined
        if not trend_messages:
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

    try:
        return _formatter.format(
            template,
            value=glucose_value, trend=trend_arrow, level=level,
            patient_name=patient_name, trend_alert=trend_alert,
        )
    except KeyError:
        return template


# ── Sensor-silence alerts ────────────────────────────────────────────────────
#
# A patient whose readings stop arriving is indistinguishable from "all good"
# unless someone says otherwise. Two escalation stages, a periodic reminder,
# and a recovery notice. Per-patient snooze (mute) is honoured here; the
# mute itself is set from the dashboard.

DEFAULT_SILENCE_CONFIG = {
    "enabled": True,
    "check_after_minutes": 60,
    "ask_after_minutes": 180,
    "remind_every_hours": 24,
}

DEFAULT_SILENCE_MESSAGES = {
    "stage1": "📡 {patient_name}: sin lecturas desde hace {silence_human} — revisa que el teléfono esté cerca del sensor",
    "stage2": "⚠️ {patient_name}: {silence_human} sin lecturas — ¿el sensor terminó su vida útil o se alejó del celular por un periodo prolongado? Si es esperado, puedes silenciar este aviso desde el dashboard",
    "reminder": "⚠️ {patient_name}: el sensor lleva {silence_human} sin reportar",
    "recovered": "🟢 {patient_name}: sensor reportando de nuevo ({value} mg/dL {trend})",
}


def get_silence_config(config: dict | None) -> dict:
    """Return the alerts.silence section merged over defaults."""
    merged = dict(DEFAULT_SILENCE_CONFIG)
    if config:
        merged.update(config.get("alerts", {}).get("silence", {}) or {})
    return merged


def silence_minutes(reading_timestamp: datetime, now: datetime | None = None) -> float:
    """Minutes elapsed since the patient's most recent reading."""
    now = now or datetime.now(timezone.utc)
    return (now - reading_timestamp).total_seconds() / 60


def is_silence_muted(silence_state: dict, now: datetime | None = None) -> bool:
    """True if the caregiver muted silence alerts and the mute is still active.

    ``muted_until`` is either an ISO timestamp or the literal ``"recovery"``
    (mute until readings resume; cleared by the recovery path in run_once).
    """
    muted_until = (silence_state or {}).get("muted_until")
    if not muted_until:
        return False
    if muted_until == "recovery":
        return True
    now = now or datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(muted_until) > now
    except (ValueError, TypeError):
        return False


def evaluate_silence(reading_timestamp: datetime, silence_state: dict,
                     config: dict | None = None,
                     now: datetime | None = None) -> str | None:
    """Decide which silence action (if any) to emit for a patient.

    Returns ``"stage1"`` (check phone/sensor), ``"stage2"`` (ask whether the
    sensor ended its life or is away), ``"reminder"`` (still silent, every
    ``remind_every_hours``), or ``None``. Recovery is handled by the caller
    when a fresh reading arrives.

    Stage transitions skip ahead naturally: a patient first evaluated after
    3h of silence gets ``stage2`` directly, without a redundant ``stage1``.
    """
    cfg = get_silence_config(config)
    if not cfg.get("enabled", True):
        return None

    silence_state = silence_state or {}
    if is_silence_muted(silence_state, now=now):
        return None

    now = now or datetime.now(timezone.utc)
    minutes = silence_minutes(reading_timestamp, now=now)
    stage = silence_state.get("stage")

    if minutes >= cfg["ask_after_minutes"]:
        if stage != "stage2":
            return "stage2"
        last = silence_state.get("last_alert_time")
        try:
            last_dt = datetime.fromisoformat(last) if last else None
        except (ValueError, TypeError):
            last_dt = None
        if last_dt is None:
            return "reminder"
        if (now - last_dt).total_seconds() >= cfg["remind_every_hours"] * 3600:
            return "reminder"
        return None

    if minutes >= cfg["check_after_minutes"]:
        return "stage1" if stage is None else None

    return None


def humanize_minutes(minutes: float) -> str:
    """Human-friendly Spanish duration: '45 min', '3h', '2 días'."""
    if minutes < 120:
        return f"{int(minutes)} min"
    hours = minutes / 60
    if hours < 48:
        return f"{int(hours)}h"
    return f"{int(hours // 24)} días"


def build_silence_message(action: str, patient_name: str, minutes: float,
                          config: dict | None = None,
                          glucose_value: int | None = None,
                          trend_arrow: str = "") -> str:
    """Render the message for a silence *action* using configurable templates.

    Templates live under ``alerts.silence.messages.<action>`` and fall back to
    Spanish defaults. Placeholders: ``{patient_name}``, ``{silence_human}``,
    ``{silence_minutes}``, and for ``recovered`` also ``{value}``/``{trend}``.
    """
    messages = {}
    if config:
        messages = config.get("alerts", {}).get("silence", {}).get("messages", {}) or {}
    template = messages.get(action) or DEFAULT_SILENCE_MESSAGES.get(action, "")
    try:
        return _formatter.format(
            template,
            patient_name=patient_name,
            silence_human=humanize_minutes(minutes),
            silence_minutes=int(minutes),
            value=glucose_value if glucose_value is not None else "",
            trend=trend_arrow,
        )
    except KeyError:
        return template
