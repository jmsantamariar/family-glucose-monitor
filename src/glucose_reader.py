"""Multi-patient glucose data reader using pylibrelinkup."""
import logging
import os
import random
import time

from pylibrelinkup import PyLibreLinkUp
from pylibrelinkup.api_url import APIUrl
from pylibrelinkup.exceptions import RedirectError

from src.crypto import decrypt_value

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


def _retry_with_backoff(
    func,
    *args,
    max_retries: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
    retryable_exceptions: tuple = (Exception,),
    non_retryable_exceptions: tuple = (),
    **kwargs,
):
    """Execute *func* with exponential backoff on retryable failures.

    Retry up to *max_retries* times.  The delay between attempts grows
    exponentially: base_delay * 2^attempt, capped at *max_delay*.
    A small random jitter (±25%) is added to avoid thundering-herd problems.

    Exceptions in *non_retryable_exceptions* are re-raised immediately without
    any retry.  If all retries are exhausted, the last exception is re-raised.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return func(*args, **kwargs)
        except non_retryable_exceptions:
            raise
        except retryable_exceptions as e:
            last_exc = e
            if attempt < max_retries:
                delay = min(base_delay * (2 ** attempt), max_delay)
                delay *= random.uniform(0.75, 1.25)
                logger.warning(
                    "Retry %d/%d after %.1fs: %s",
                    attempt + 1,
                    max_retries,
                    delay,
                    type(e).__name__,
                )
                time.sleep(delay)
            else:
                logger.error("Exhausted %d retries: %s", max_retries, type(e).__name__)
    raise last_exc  # type: ignore[misc]


def _build_client(email: str, password: str, region: str) -> PyLibreLinkUp:
    api_url = REGION_MAP.get(region.upper(), APIUrl.EU)
    client = PyLibreLinkUp(email=email, password=password, api_url=api_url)
    try:
        _retry_with_backoff(
            client.authenticate,
            max_retries=3,
            base_delay=2.0,
            non_retryable_exceptions=(RedirectError,),
        )
    except RedirectError as e:
        logger.info("Redirect to region %s, re-authenticating", e.region)
        client = PyLibreLinkUp(email=email, password=password, api_url=e.region)
        _retry_with_backoff(
            client.authenticate,
            max_retries=3,
            base_delay=2.0,
            non_retryable_exceptions=(RedirectError,),
        )
    return client


# Session reuse (2026-11-19). The daemon used to log in again on EVERY cycle (288 logins/day). Since
# 2026-11-12 LibreLinkUp rejects ~1 in 4 logins with {'code': 60, 'message': 'locked'} (pylibrelinkup
# reports it as AuthenticationError), and ~28% of cycles returned no readings and fired no alerts.
# Calls made with an already-issued token never failed in that period. So: keep the authenticated
# client across cycles, refresh it after SESSION_MAX_AGE_S, and if a cycle fails while using a reused
# session, drop it and log in again in the same cycle (= the old behaviour, never worse).
SESSION_MAX_AGE_S = 6 * 3600

_session: dict = {"client": None, "key": None, "since": 0.0}


def _reset_session() -> None:
    _session.update(client=None, key=None, since=0.0)


def _get_client(email: str, password: str, region: str) -> tuple[PyLibreLinkUp, bool]:
    """-> (client, fresh). Reuses the cached authenticated client while it is young enough and was
    built for the same account and region; otherwise logs in."""
    key = (email, hash(password), region)
    now = time.monotonic()
    if (_session["client"] is not None and _session["key"] == key
            and now - _session["since"] < SESSION_MAX_AGE_S):
        return _session["client"], False
    _reset_session()
    client = _build_client(email, password, region)
    _session.update(client=client, key=key, since=now)
    return client, True


def read_all_patients(config: dict) -> list[dict]:
    try:
        email = os.environ.get("LIBRELINKUP_EMAIL") or config["librelinkup"]["email"]
        password = os.environ.get("LIBRELINKUP_PASSWORD") or decrypt_value(config["librelinkup"]["password"])
        region = config.get("librelinkup", {}).get("region", "EU")
        client, fresh = _get_client(email, password, region)
    except Exception as e:
        _reset_session()
        logger.error("Failed to read glucose data: %s: %s", type(e).__name__, e)
        return []
    logger.info("Authentication successful" if fresh else "Reusing LibreLinkUp session")
    readings = _read_with_client(client, config)
    if readings is None and not fresh:
        # The reused session may have expired or been revoked: one fresh login, same cycle.
        logger.warning("Reused LibreLinkUp session failed; logging in again")
        _reset_session()
        try:
            client, _ = _get_client(email, password, region)
        except Exception as e:
            _reset_session()
            logger.error("Failed to read glucose data: %s: %s", type(e).__name__, e)
            return []
        logger.info("Authentication successful")
        readings = _read_with_client(client, config)
    if readings is None:
        _reset_session()
        return []
    return readings


def _read_with_client(client: PyLibreLinkUp, config: dict) -> list[dict] | None:
    """-> readings, or None when the session looks unusable: get_patients failed, or it listed
    patients and EVERY per-patient read raised."""
    retry_cfg = config.get("librelinkup", {}).get("retry", {})
    patients_max_retries: int = retry_cfg.get("max_retries", 2)
    patients_base_delay: float = retry_cfg.get("base_delay", 2.0)
    patients_max_delay: float = retry_cfg.get("max_delay", 60.0)
    try:
        patients = _retry_with_backoff(
            client.get_patients,
            max_retries=patients_max_retries,
            base_delay=patients_base_delay,
            max_delay=patients_max_delay,
        )
    except Exception as e:
        logger.error("Failed to read glucose data: %s: %s", type(e).__name__, e)
        return None
    try:
        if not patients:
            logger.error("No patients found in LibreLinkUp account")
            return []
        logger.info("Found %d patient(s)", len(patients))
        readings = []
        errors = 0
        for patient in patients:
            patient_name = f"{patient.first_name} {patient.last_name}"
            try:
                latest = _retry_with_backoff(
                    client.latest,
                    patient,
                    max_retries=2,
                    base_delay=patients_base_delay,
                    max_delay=patients_max_delay,
                )
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
                errors += 1
                logger.error(
                    "Failed to read data for %s: %s: %s", patient_name, type(e).__name__, e
                )
        if errors == len(patients):
            return None
        return readings
    except Exception as e:
        logger.error("Failed to read glucose data: %s: %s", type(e).__name__, e)
        return None
