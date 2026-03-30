"""Configuration schema validation for family-glucose-monitor.

Validates that the loaded config.yaml has all required fields with correct types,
logical consistency between thresholds, and at least one enabled output.
"""
import os
import re
from typing import Any


_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def _check_email_format(email: str) -> bool:
    return bool(_EMAIL_RE.match(email))


def validate_config(config: Any) -> list[str]:
    """Validate configuration dictionary.

    Returns a list of error strings. An empty list means the config is valid.
    """
    if not isinstance(config, dict):
        return ["config must be a YAML mapping (dict)"]

    errors: list[str] = []

    # --- librelinkup section ---
    ll = config.get("librelinkup")
    if not isinstance(ll, dict):
        errors.append("Missing required section: librelinkup")
    else:
        email = ll.get("email") or os.environ.get("LIBRELINKUP_EMAIL", "")
        password = ll.get("password") or os.environ.get("LIBRELINKUP_PASSWORD", "")

        if not email:
            errors.append(
                "librelinkup.email is required "
                "(or set the LIBRELINKUP_EMAIL environment variable)"
            )
        elif email and not _check_email_format(str(email)):
            errors.append(
                f"librelinkup.email does not look like a valid email address: {email!r}"
            )

        if not password:
            errors.append(
                "librelinkup.password is required "
                "(or set the LIBRELINKUP_PASSWORD environment variable)"
            )

    # --- alerts section ---
    alerts = config.get("alerts")
    if not isinstance(alerts, dict):
        errors.append("Missing required section: alerts")
    else:
        low = alerts.get("low_threshold")
        high = alerts.get("high_threshold")
        cooldown = alerts.get("cooldown_minutes")
        max_age = alerts.get("max_reading_age_minutes")

        if low is None:
            errors.append("alerts.low_threshold is required")
        elif not isinstance(low, (int, float)):
            errors.append(f"alerts.low_threshold must be a number, got {type(low).__name__}")
        elif low <= 0:
            errors.append(f"alerts.low_threshold must be positive, got {low}")

        if high is None:
            errors.append("alerts.high_threshold is required")
        elif not isinstance(high, (int, float)):
            errors.append(f"alerts.high_threshold must be a number, got {type(high).__name__}")
        elif high <= 0:
            errors.append(f"alerts.high_threshold must be positive, got {high}")

        if (
            isinstance(low, (int, float))
            and isinstance(high, (int, float))
            and low > 0
            and high > 0
            and low >= high
        ):
            errors.append(
                f"alerts.low_threshold ({low}) must be less than alerts.high_threshold ({high})"
            )

        if cooldown is None:
            errors.append("alerts.cooldown_minutes is required")
        elif not isinstance(cooldown, (int, float)):
            errors.append(
                f"alerts.cooldown_minutes must be a number, got {type(cooldown).__name__}"
            )
        elif cooldown <= 0:
            errors.append(f"alerts.cooldown_minutes must be > 0, got {cooldown}")

        if max_age is None:
            errors.append("alerts.max_reading_age_minutes is required")
        elif not isinstance(max_age, (int, float)):
            errors.append(
                f"alerts.max_reading_age_minutes must be a number, got {type(max_age).__name__}"
            )
        elif max_age <= 0:
            errors.append(f"alerts.max_reading_age_minutes must be > 0, got {max_age}")

        # --- alerts.trend (optional) ---
        trend = alerts.get("trend")
        if trend is not None:
            if not isinstance(trend, dict):
                errors.append("alerts.trend must be a mapping (dict)")
            else:
                if "enabled" in trend and not isinstance(trend["enabled"], bool):
                    errors.append(
                        f"alerts.trend.enabled must be a boolean, got {type(trend['enabled']).__name__}"
                    )
                for field in ("low_approaching_threshold", "high_approaching_threshold"):
                    val = trend.get(field)
                    if val is not None:
                        if not isinstance(val, (int, float)):
                            errors.append(
                                f"alerts.trend.{field} must be a number, got {type(val).__name__}"
                            )
                        elif val <= 0:
                            errors.append(f"alerts.trend.{field} must be positive, got {val}")
                trend_messages = trend.get("messages")
                if trend_messages is not None:
                    if not isinstance(trend_messages, dict):
                        errors.append("alerts.trend.messages must be a mapping (dict)")
                    else:
                        for key, tmpl in trend_messages.items():
                            if not isinstance(tmpl, str):
                                errors.append(
                                    f"alerts.trend.messages.{key} must be a string, got {type(tmpl).__name__}"
                                )

    # --- outputs section: at least one must be enabled ---
    outputs = config.get("outputs", [])
    if not isinstance(outputs, list):
        errors.append("outputs must be a list")
    else:
        enabled_outputs = [o for o in outputs if isinstance(o, dict) and o.get("enabled")]
        if not enabled_outputs:
            errors.append(
                "At least one output must be enabled in the outputs list "
                "(telegram, webhook, or whatsapp)"
            )
        for i, out in enumerate(outputs):
            if not isinstance(out, dict):
                errors.append(f"outputs[{i}] must be a mapping (dict)")
                continue
            out_type = out.get("type")
            if out_type not in ("telegram", "webhook", "whatsapp", None):
                errors.append(
                    f"outputs[{i}].type {out_type!r} is not a recognised output type"
                )

    return errors
