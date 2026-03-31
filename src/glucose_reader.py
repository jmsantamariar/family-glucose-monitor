"""Multi-patient glucose data reader using pylibrelinkup."""
import logging
import os

from pylibrelinkup import PyLibreLinkUp
from pylibrelinkup.api_url import APIUrl
from pylibrelinkup.exceptions import RedirectError

logger = logging.getLogger(__name__)

REGION_MAP = {
    "US": APIUrl.US,
    "EU": APIUrl.EU,
    "EU2": APIUrl.EU2,
    "DE": APIUrl.DE,
    "FR": APIUrl.FR,
    "JP": APIUrl.JP,
    "AP": APIUrl.AP,
    "AU": APIUrl.AU,
    "AE": APIUrl.AE,
    "CA": APIUrl.CA,
    "LA": APIUrl.LA,
    "RU": APIUrl.RU,
}


def _build_client(email: str, password: str, region: str) -> PyLibreLinkUp:
    api_url = REGION_MAP.get(region.upper(), APIUrl.US)
    client = PyLibreLinkUp(email=email, password=password, api_url=api_url)
    try:
        client.authenticate()
    except RedirectError as e:
        logger.info("Redirect to region %s, re-authenticating", e.region)
        client = PyLibreLinkUp(email=email, password=password, api_url=e.region)
        client.authenticate()
    return client


def read_all_patients(config: dict) -> list[dict]:
    try:
        email = os.environ.get("LIBRELINKUP_EMAIL") or config["librelinkup"]["email"]
        password = os.environ.get("LIBRELINKUP_PASSWORD") or config["librelinkup"]["password"]
        region = config.get("librelinkup", {}).get("region", "US")
        client = _build_client(email, password, region)
        logger.info("Authentication successful")
        patients = client.get_patients()
        if not patients:
            logger.error("No patients found in LibreLinkUp account")
            return []
        logger.info("Found %d patient(s)", len(patients))
        readings = []
        for patient in patients:
            patient_name = f"{patient.first_name} {patient.last_name}"
            try:
                latest = client.latest(patient)
                if latest is None:
                    logger.warning("No glucose data for %s", patient_name)
                    continue
                readings.append({
                    "patient_id": str(patient.patient_id),
                    "patient_name": patient_name,
                    "value": int(latest.value),
                    "timestamp": latest.factory_timestamp,
                    "trend_name": latest.trend.name,
                    "trend_arrow": latest.trend.indicator,
                    "is_high": latest.is_high,
                    "is_low": latest.is_low,
                })
                logger.info(
                    "  %s: %d mg/dL %s", patient_name, int(latest.value), latest.trend.indicator
                )
            except Exception as e:
                logger.error(
                    "Failed to read data for %s: %s: %s", patient_name, type(e).__name__, e
                )
        return readings
    except Exception as e:
        logger.error("Failed to read glucose data: %s: %s", type(e).__name__, e)
        return []
