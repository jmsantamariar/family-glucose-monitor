"""Read glucose data from all linked patients via LibreLinkUp."""
import logging
import os
from datetime import datetime, timezone

from pylibrelinkup import PyLibreLinkUp

logger = logging.getLogger(__name__)


def read_all_patients(config: dict) -> list[dict]:
    """Authenticate with LibreLinkUp and read latest glucose for ALL patients."""
    ll_config = config.get("librelinkup", {})
    email = ll_config.get("email") or os.environ.get("LIBRELINKUP_EMAIL", "")
    password = ll_config.get("password") or os.environ.get("LIBRELINKUP_PASSWORD", "")
    region = ll_config.get("region", "EU")

    if not email or not password:
        logger.error("LibreLinkUp credentials not configured")
        return []

    try:
        client = PyLibreLinkUp(email=email, password=password)
        client.authenticate()
    except Exception as e:
        logger.error("LibreLinkUp authentication failed: %s", e)
        return []

    try:
        patients = client.get_patients()
    except Exception as e:
        logger.error("Failed to get patients: %s", e)
        return []

    if not patients:
        logger.warning("No patients found in LibreLinkUp account")
        return []

    readings = []
    for patient in patients:
        try:
            latest = client.latest(patient)
            if latest is None:
                logger.warning("No latest reading for %s %s", patient.first_name, patient.last_name)
                continue

            timestamp = latest.factory_timestamp
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)

            reading = {
                "patient_id": str(patient.patient_id),
                "patient_name": f"{patient.first_name} {patient.last_name}".strip(),
                "value": int(latest.value),
                "trend_arrow": latest.trend.indicator if hasattr(latest, 'trend') and latest.trend else "→",
                "timestamp": timestamp,
                "is_high": getattr(latest, 'is_high', False),
                "is_low": getattr(latest, 'is_low', False),
            }
            readings.append(reading)
        except Exception as e:
            logger.error("Error reading patient %s: %s", patient.patient_id, e)

    logger.info("Read %d patient(s) successfully", len(readings))
    return readings
