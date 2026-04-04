"""FastAPI REST API server for external consumption (widgets, dashboards, etc.).

This module provides the **external read-only API** whose routes are distinct
from the authenticated dashboard served by ``src/api.py``:

* ``src/api.py``        — Authenticated internal dashboard (login, setup, patient
                          cache, alert history).  Runs on the dashboard port
                          (default 8080).  All routes require a session cookie.
* ``src/api_server.py`` — External read-only REST API backed by the
                          ``readings_cache.json`` file written by the polling
                          daemon.  Intended for widgets, Home Assistant, or other
                          local integrations.  Runs on a separate port (default
                          8081, configurable).

**Authentication — secure by default**

The external API requires an ``Authorization: Bearer <key>`` header by default.
Set the ``API_KEY`` environment variable to a strong random secret.

For local development or trusted networks only, you may opt out of authentication
by setting ``ALLOW_INSECURE_LOCAL_API=1``.  This must be done explicitly and
should **never** be enabled in production, as the API exposes health data.

Route contracts are intentionally different:

* ``/api/health`` here returns ``patient_count`` / ``updated_at`` /
  ``cache_age_seconds`` (file-cache freshness).
* ``/api/health`` in ``api.py`` returns ``patients_monitored`` / ``timestamp``
  (in-memory cache snapshot).

CORS origins are restricted by default.  Set the ``CORS_ALLOWED_ORIGINS``
environment variable to a comma-separated list of allowed origins when the API
needs to be reached from a browser on a different origin, e.g.::

    CORS_ALLOWED_ORIGINS=http://localhost:3000,https://dashboard.example.com
"""
import hmac
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml
from fastapi import FastAPI, HTTPException, Request, Query, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.alert_history import get_alerts, validate_schema
from src.paths import get_cache_path, get_db_path as _paths_get_db_path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_config: dict = {}

# --- Authentication configuration ---
# Secure by default: API_KEY is required.
# Set ALLOW_INSECURE_LOCAL_API=1 only for local/dev environments to bypass auth.
API_KEY: str | None = os.environ.get("API_KEY") or None
ALLOW_INSECURE_LOCAL_API: bool = os.environ.get("ALLOW_INSECURE_LOCAL_API") == "1"

# Loopback addresses — enforced when ALLOW_INSECURE_LOCAL_API is set.
_LOOPBACK_ADDRS: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost"})

_bearer_scheme = HTTPBearer(auto_error=False)


def _require_api_key(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
) -> None:
    """Dependency that enforces API key authentication.

    - When ``API_KEY`` is set: the caller must supply a matching
      ``Authorization: Bearer <key>`` header.
    - When ``API_KEY`` is unset and ``ALLOW_INSECURE_LOCAL_API=1``: unauthenticated
      access is allowed (development/local use only).
    - When ``API_KEY`` is unset and ``ALLOW_INSECURE_LOCAL_API`` is not set:
      all requests are rejected with 401 to prevent accidental data exposure.
    """
    if API_KEY is not None:
        if credentials is None or not hmac.compare_digest(credentials.credentials, API_KEY):
            raise HTTPException(status_code=401, detail="Invalid or missing API key.")
        return
    # No API_KEY configured — check explicit opt-out flag.
    if not ALLOW_INSECURE_LOCAL_API:
        raise HTTPException(
            status_code=401,
            detail=(
                "API authentication is required. "
                "Set the API_KEY environment variable, or set "
                "ALLOW_INSECURE_LOCAL_API=1 for local/development use only."
            ),
        )


def _load_config_file() -> dict:
    config_path = PROJECT_ROOT / "config.yaml"
    with open(config_path) as f:
        parsed = yaml.safe_load(f)
    if not isinstance(parsed, dict):
        return {}
    return parsed


def get_db_path() -> str:
    """Resolve the alert history DB path.

    Delegates to :func:`src.paths.get_db_path` with the runtime-loaded
    ``_config`` so that the resolution priority (env > config > default)
    is consistent across all modules.
    """
    return _paths_get_db_path(_config)


@asynccontextmanager
async def lifespan(application: "FastAPI"):
    global _config
    try:
        _config = _load_config_file()
    except FileNotFoundError:
        logger.warning("config.yaml not found, using defaults for cache path")
    except yaml.YAMLError as exc:
        logger.warning("config.yaml is invalid YAML, using defaults for cache path: %s", exc)

    # Preflight: validate alert_history.db schema if the file already exists.
    db_path = get_db_path()
    schema_errors = validate_schema(db_path)
    if schema_errors:
        detail = "\n  ".join(schema_errors)
        logger.error(
            "alert_history.db schema mismatch — API server cannot start safely:\n  %s\n"
            "Delete the database file and restart to re-initialise it, "
            "or run Alembic migrations to upgrade the schema.",
            detail,
        )
        raise RuntimeError(f"alert_history.db schema mismatch: {schema_errors[0]}")

    if API_KEY is None:
        if ALLOW_INSECURE_LOCAL_API:
            logger.warning(
                "ALLOW_INSECURE_LOCAL_API=1 — external API is running without "
                "authentication. Requests are restricted to loopback (127.0.0.1 / ::1). "
                "This should only be used in local/dev environments."
            )
        else:
            logger.error(
                "API_KEY is not set and ALLOW_INSECURE_LOCAL_API is not enabled. "
                "All API requests will be rejected. "
                "Set API_KEY to enable authenticated access, or set "
                "ALLOW_INSECURE_LOCAL_API=1 for local/development use only."
            )
    yield


app = FastAPI(
    title="Family Glucose Monitor API",
    description="REST API for external consumption of glucose readings (widgets, dashboards, etc.)",
    version="1.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS — restricted by default to protect health data.
# Override via the CORS_ALLOWED_ORIGINS environment variable.
# ---------------------------------------------------------------------------
_cors_origins_raw = os.environ.get("CORS_ALLOWED_ORIGINS", "")
_cors_origins: list[str] = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Add HTTP security headers to every response."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.middleware("http")
async def loopback_guardrail_middleware(request: Request, call_next):
    """Reject non-loopback clients when ALLOW_INSECURE_LOCAL_API is enabled.

    When ``ALLOW_INSECURE_LOCAL_API=1`` the external API runs without any
    bearer-token authentication.  To prevent accidental exposure on a LAN or
    the public internet, requests from addresses outside the loopback range
    (127.0.0.1 / ::1) are rejected with ``403 Forbidden``.
    """
    if ALLOW_INSECURE_LOCAL_API and API_KEY is None:
        client_host = request.client.host if request.client else None
        # Allow when client host cannot be determined (e.g. WSGI test clients).
        if client_host is not None and client_host not in _LOOPBACK_ADDRS:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=403,
                content={
                    "detail": (
                        "ALLOW_INSECURE_LOCAL_API is enabled. "
                        "Access is restricted to loopback addresses (127.0.0.1 / ::1). "
                        "Set API_KEY to allow remote access."
                    )
                },
            )
    return await call_next(request)


def _load_cache() -> dict:
    """Load the readings cache from disk. Returns empty structure on missing/invalid file."""
    cache_file = get_cache_path(_config)
    try:
        with open(cache_file) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"readings": [], "updated_at": None}
    except json.JSONDecodeError:
        logger.warning("readings_cache.json is corrupted, returning empty cache")
        return {"readings": [], "updated_at": None}


@app.get("/api/readings")
def get_all_readings(_: None = Security(_require_api_key)):
    """Return all cached patient glucose readings."""
    cache = _load_cache()
    return {
        "readings": cache.get("readings", []),
        "updated_at": cache.get("updated_at"),
    }


@app.get("/api/readings/{patient_id}")
def get_patient_reading(patient_id: str, _: None = Security(_require_api_key)):
    """Return the latest glucose reading for a specific patient."""
    cache = _load_cache()
    readings = cache.get("readings", [])
    for reading in readings:
        if reading.get("patient_id") == patient_id:
            return reading
    raise HTTPException(status_code=404, detail=f"Patient '{patient_id}' not found in cache")


@app.get("/api/health")
def get_health(_: None = Security(_require_api_key)):
    """Return API health status and data freshness information."""
    cache = _load_cache()
    updated_at = cache.get("updated_at")
    patient_count = len(cache.get("readings", []))

    age_seconds: float | None = None
    if updated_at:
        try:
            last_update = datetime.fromisoformat(updated_at)
            age_seconds = (datetime.now(timezone.utc) - last_update).total_seconds()
        except ValueError:
            age_seconds = None

    return {
        "status": "ok",
        "patient_count": patient_count,
        "updated_at": updated_at,
        "cache_age_seconds": age_seconds,
    }


@app.get("/api/alerts")
def get_alert_history(patient_id: Optional[str] = None, hours: int = Query(default=24, ge=1, le=168), _: None = Security(_require_api_key)):
    """Return alert history for the last *hours* hours (max 168 = 1 week).

    Optionally filter by *patient_id*.  Returns an empty list when there are no
    alerts or the database does not exist yet.
    """
    alerts = get_alerts(get_db_path(), patient_id=patient_id, hours=hours)
    return alerts
