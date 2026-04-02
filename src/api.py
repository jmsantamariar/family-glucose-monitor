"""FastAPI web server for the authenticated glucose monitoring dashboard.

This is the **internal** authenticated application.  All routes (except the
setup wizard and login pages) require a valid session cookie.

Responsibilities
----------------
* Serve the dashboard UI (``/``, ``/login``, ``/setup``).
* Handle authentication: setup wizard, login, logout.
* Maintain an in-memory cache of the latest patient readings, reloaded from
  ``readings_cache.json`` on demand whenever the file changes (mtime-based).
* Expose internal API routes: ``/api/patients``, ``/api/health``,
  ``/api/alerts``.

Contrast with ``src/api_server.py``
------------------------------------
``src/api_server.py`` is the **external read-only REST API** intended for
widgets, Home Assistant, or other local integrations.  It serves a different
port (configurable), has no authentication, and reads data from the
``readings_cache.json`` file written by the main polling daemon.  Its
``/api/health`` response schema differs (``patient_count`` / ``updated_at`` /
``cache_age_seconds``) from this module's schema (``patients_monitored`` /
``timestamp``).  Both modules now share ``readings_cache.json`` as the single
source of truth.
"""
import json
import logging
import os
import secrets
import stat
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi import Query

from src import alert_engine
from src.alert_history import get_alerts
from src.auth import hash_password, is_configured, session_manager, verify_credentials
from src.config_schema import validate_config as schema_validate_config
from src.crypto import encrypt_value
from src.setup_status import is_setup_complete

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# In-memory cache of latest readings per patient (keyed by patient_id)
_readings_cache: dict = {}
_cache_lock = threading.Lock()
_config: dict = {}
_last_mtime: float = 0.0

# External polling state — governed by main.py in 'full' mode.
# Use a dedicated lock to avoid coupling with _cache_lock.
_external_polling: bool = False
_external_last_payload: list | None = None
_external_lock = threading.Lock()


def set_external_polling(enabled: bool) -> None:
    """Signal that an external caller (main.py) will manage the polling loop.

    When *enabled* is True the ``lifespan`` handler will skip starting
    ``_poll_loop`` so that ``main.py`` remains the single source of truth for
    LibreLinkUp API requests.
    """
    global _external_polling
    with _external_lock:
        _external_polling = bool(enabled)


def update_readings_cache(payload: list | None = None) -> None:
    """Signal that new readings are available and invalidate the mtime cache.

    Called by ``main.py`` immediately after every ``run_once()`` cycle so
    that the next dashboard request always reads the freshest data from the
    cache file, even when the file mtime did not change (same-second write).

    *payload* is optional:

    * If provided, it is stored as ``_external_last_payload`` so that
      ``_load_and_enrich_cache()`` can use it as an additional invalidation
      signal when ``_external_polling`` is enabled.
    * Whether or not *payload* is given, ``_last_mtime`` is reset to ``0.0``
      so the next call to ``_load_and_enrich_cache()`` always re-reads the
      cache file rather than relying solely on a potentially stale mtime.
    """
    global _external_last_payload, _last_mtime
    with _external_lock:
        _external_last_payload = payload
    with _cache_lock:
        _last_mtime = 0.0
    logger.debug("Dashboard cache invalidated; will reload from file on next request")

APP_ENV = os.environ.get("APP_ENV") or os.environ.get("ENV") or "production"
_ALLOW_AUTH_DISABLED = (
    os.environ.get("AUTH_DISABLED") == "1"
    and APP_ENV.lower() in {"dev", "development", "local", "test"}
)
_IS_DEV = APP_ENV.lower() in {"dev", "development", "local", "test"}
# Secure cookies require HTTPS — only enforced in non-development environments.
_SECURE_COOKIES = not _IS_DEV
if os.environ.get("AUTH_DISABLED") == "1" and not _ALLOW_AUTH_DISABLED:
    logger.warning(
        "AUTH_DISABLED=1 ignorado porque APP_ENV/ENV=%s no es un entorno de desarrollo",
        APP_ENV,
    )

# ── CSRF helpers ──────────────────────────────────────────────────────────────

_CSRF_COOKIE = "csrf_token"
_CSRF_HEADER = "X-CSRF-Token"

# POST endpoints that are intentionally exempt from CSRF validation because
# they are pre-authentication (no session exists yet to forge).
_CSRF_EXEMPT_PATHS = {"/api/login"}


def _generate_csrf_token() -> str:
    """Return a cryptographically random CSRF token."""
    return secrets.token_hex(32)


def _set_csrf_cookie(response: Response, token: str) -> None:
    """Attach the CSRF token as a non-httponly cookie so JS can read it."""
    response.set_cookie(
        key=_CSRF_COOKIE,
        value=token,
        httponly=False,  # JS must be able to read this to send it as a header
        secure=_SECURE_COOKIES,
        samesite="strict",
        path="/",
        max_age=86400,
    )


def _validate_csrf(request: Request) -> None:
    """Raise 403 if the CSRF token in the cookie does not match the request header.

    Skipped when ``_ALLOW_AUTH_DISABLED`` is True (tests / dev environment).
    Skipped for GET/HEAD/OPTIONS requests (idempotent).
    Skipped for paths in ``_CSRF_EXEMPT_PATHS`` (pre-auth endpoints).
    """
    if _ALLOW_AUTH_DISABLED:
        return
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    if request.url.path in _CSRF_EXEMPT_PATHS:
        return

    cookie_token = request.cookies.get(_CSRF_COOKIE)
    header_token = request.headers.get(_CSRF_HEADER)
    if not cookie_token or not header_token or cookie_token != header_token:
        raise HTTPException(status_code=403, detail="CSRF validation failed.")


def load_config(path: str = "config.yaml") -> dict:
    resolved = path if os.path.isabs(path) else str(PROJECT_ROOT / path)
    with open(resolved) as f:
        return yaml.safe_load(f)

# ── Login rate limiter ────────────────────────────────────────────────────────

_LOGIN_MAX_ATTEMPTS = 10
_LOGIN_WINDOW_SECONDS = 600  # 10 minutes


def _check_rate_limit(ip: str) -> bool:
    """Return True if the IP is allowed to attempt login, False if rate-limited."""
    count = session_manager.get_recent_failed_logins(ip, _LOGIN_WINDOW_SECONDS)
    return count < _LOGIN_MAX_ATTEMPTS


def _record_failed_login(ip: str) -> None:
    """Record a failed login attempt for the given IP."""
    session_manager.record_failed_login(ip)


def _reset_login_failures(ip: str) -> None:
    """Clear failed login counter for the given IP on successful login."""
    session_manager.clear_failed_logins(ip)

@asynccontextmanager
async def lifespan(application: "FastAPI"):
    global _config
    try:
        _config = load_config()
    except FileNotFoundError:
        logger.warning("config.yaml not found, dashboard will start without active config")

    def _session_cleanup_loop():
        while True:
            time.sleep(3600)
            try:
                removed = session_manager.cleanup_expired()
                if removed:
                    logger.debug("Cleaned up %d expired session(s)", removed)
            except Exception as exc:
                logger.warning("Session cleanup failed: %s", exc)
            try:
                session_manager.cleanup_old_login_attempts(window_seconds=_LOGIN_WINDOW_SECONDS)
            except Exception as exc:
                logger.warning("Login attempts cleanup failed: %s", exc)

    cleanup_thread = threading.Thread(target=_session_cleanup_loop, daemon=True)
    cleanup_thread.start()
    yield

app = FastAPI(title="Family Glucose Monitor", version="1.0.0", lifespan=lifespan)

# ── Authentication middleware ─────────────────────────────────────────────────

_AUTH_EXEMPT_PATHS = {
    "/api/setup",
    "/api/login",
    "/api/setup/status",
    "/api/logout",
    "/login",
    "/setup",
}

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Enforce session authentication on all protected routes."""
    if _ALLOW_AUTH_DISABLED:
        return await call_next(request)

    if request.url.path in _AUTH_EXEMPT_PATHS:
        return await call_next(request)

    token = request.cookies.get("session_token")
    if session_manager.is_valid(token):
        return await call_next(request)

    # If setup is complete, or a config file already exists, direct users to login
    # so they can authenticate and recover from a broken/partial setup.
    if is_setup_complete() or is_configured():
        return RedirectResponse(url="/login", status_code=302)
    # Fresh install with no existing config: send users to the setup wizard.
    return RedirectResponse(url="/setup", status_code=302)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Add HTTP security headers to every response."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


def _get_cache_path() -> str:
    """Return the absolute path to the readings cache file."""
    cache_path = _config.get("api", {}).get("cache_file", "readings_cache.json")
    if not os.path.isabs(cache_path):
        cache_path = str(PROJECT_ROOT / cache_path)
    return cache_path


def _load_and_enrich_cache() -> None:
    """Reload readings from ``readings_cache.json`` if the file has changed.

    Uses ``os.path.getmtime()`` to detect modifications so that the
    in-memory cache is only rebuilt when the underlying file is newer than
    the last load.  If the file does not exist or contains invalid JSON the
    cache is cleared and the mtime marker is updated so we do not spam the
    log on every request.

    When ``_external_polling`` is enabled and ``update_readings_cache()`` has
    been called since the last load (indicated by ``_external_last_payload``
    being non-``None``), ``_last_mtime`` is reset to ``0.0`` before the mtime
    comparison so that same-second file writes are never missed.
    """
    global _last_mtime, _external_last_payload

    cache_path = _get_cache_path()

    try:
        mtime = os.path.getmtime(cache_path)
    except OSError:
        # File does not exist — clear cache and reset mtime so that when the
        # file is re-created (even with a previously-seen mtime) we always
        # detect it as new.
        with _cache_lock:
            _readings_cache.clear()
            _last_mtime = 0.0
        return

    # If external polling flagged an update, force re-read regardless of mtime.
    # This guards against same-second writes where mtime alone would not change.
    force_reload = False
    with _external_lock:
        if _external_polling and _external_last_payload is not None:
            _external_last_payload = None
            force_reload = True
    if force_reload:
        with _cache_lock:
            _last_mtime = 0.0

    with _cache_lock:
        if mtime == _last_mtime:
            return  # File unchanged; nothing to do

    try:
        with open(cache_path) as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read readings_cache.json: %s", exc)
        with _cache_lock:
            _readings_cache.clear()
            _last_mtime = mtime
        return

    readings = payload.get("readings", [])
    new_cache: dict = {}
    for r in readings:
        pid = r.get("patient_id")
        if not pid:
            continue
        glucose = r.get("value", 0)
        trend_arrow = r.get("trend_arrow", "")
        try:
            level = alert_engine.evaluate(glucose, _config)
        except (KeyError, TypeError):
            level = "normal"
        try:
            trend_alert = alert_engine.evaluate_trend(glucose, trend_arrow, _config)
        except (KeyError, TypeError):
            trend_alert = "normal"
        r["glucose_value"] = glucose
        r["level"] = level
        r["trend_alert"] = trend_alert
        r["color"] = _get_color(level, trend_alert)
        r["fetched_at"] = datetime.now(timezone.utc).isoformat()
        new_cache[pid] = r

    with _cache_lock:
        if mtime > _last_mtime:
            _readings_cache.clear()
            _readings_cache.update(new_cache)
            _last_mtime = mtime
    logger.debug("Loaded %d readings from cache file", len(new_cache))


def _get_color(level: str, trend_alert: str) -> str:
    """Return semaphore color: red, yellow, green."""
    if level in ("low", "high") or trend_alert == "falling_fast":
        return "red"
    if trend_alert in ("falling", "rising_fast"):
        return "yellow"
    return "green"

@app.get("/api/patients", response_class=JSONResponse)
def get_patients():
    """Return all patients with their latest readings."""
    _load_and_enrich_cache()
    with _cache_lock:
        patients = list(_readings_cache.values())
    return {"patients": patients, "count": len(patients)}

@app.get("/api/patients/{patient_id}", response_class=JSONResponse)
def get_patient(patient_id: str):
    """Return a specific patient's latest reading."""
    _load_and_enrich_cache()
    with _cache_lock:
        reading = _readings_cache.get(patient_id)
    if not reading:
        raise HTTPException(status_code=404, detail="Patient not found")
    return reading

@app.get("/api/health", response_class=JSONResponse)
def health_check():
    """Health check endpoint.

    Returns a unified schema consistent with ``src/api_server.py``::

        {
            "status": "ok",
            "patient_count": <int>,
            "updated_at": "<ISO-8601 UTC>",
            "cache_age_seconds": null
        }

    ``cache_age_seconds`` is always ``null`` for the dashboard API because
    readings are kept in-memory and there is no cache-file mtime to compare.
    """
    _load_and_enrich_cache()
    with _cache_lock:
        patient_count = len(_readings_cache)
    return {
        "status": "ok",
        "patient_count": patient_count,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "cache_age_seconds": None,
    }

@app.get("/api/alerts", response_class=JSONResponse)
def get_alert_history(patient_id: Optional[str] = None, hours: int = Query(default=24, ge=1, le=8760)):
    """Return alert history for the last *hours* hours.

    Optionally filter by *patient_id*.  Returns an empty list when there are no
    alerts or the database does not exist yet.
    """
    db_path = _config.get("alert_history_db", "alert_history.db")
    if not os.path.isabs(db_path):
        db_path = str(PROJECT_ROOT / db_path)
    alerts = get_alerts(db_path, patient_id=patient_id, hours=hours)
    return alerts

@app.get("/", response_class=HTMLResponse)
def dashboard():
    """Serve the dashboard HTML page."""
    html_path = Path(__file__).parent / "dashboard" / "index.html"
    if not html_path.exists():
        raise HTTPException(status_code=500, detail="Dashboard HTML not found")
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))

# ── Auth / Setup routes ───────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
def login_page():
    """Serve the login page. Redirects to /setup if not yet configured."""
    if not is_configured():
        return RedirectResponse(url="/setup", status_code=302)
    html_path = Path(__file__).parent / "dashboard" / "login.html"
    if not html_path.exists():
        raise HTTPException(status_code=500, detail="Login HTML not found")
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))

@app.get("/setup", response_class=HTMLResponse)
def setup_page():
    """Serve the setup wizard page."""
    html_path = Path(__file__).parent / "dashboard" / "setup.html"
    if not html_path.exists():
        raise HTTPException(status_code=500, detail="Setup HTML not found")
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))

@app.get("/api/setup/status", response_class=JSONResponse)
def setup_status():
    """Return whether the system has already been configured."""
    return {"configured": is_setup_complete()}

@app.post("/api/login", response_class=JSONResponse)
async def api_login(request: Request, response: Response):
    """Validate credentials against dashboard_auth in config.yaml and issue a session cookie.

    Accepts ``username`` (or the legacy ``email`` field as an alias) and
    ``password``.  Credentials are verified against the ``dashboard_auth``
    section — **not** the LibreLinkUp credentials.
    """    
    client_ip = request.client.host if request.client else "__no_client__"

    if not _check_rate_limit(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Demasiados intentos. Intenta de nuevo más tarde.",
        )

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON inválido")

    # Accept both "username" and legacy "email" field
    username = str(data.get("username") or data.get("email", ""))
    password = str(data.get("password", ""))

    if not verify_credentials(username, password):
        _record_failed_login(client_ip)
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")

    _reset_login_failures(client_ip)
    token = session_manager.create_session()
    csrf_token = _generate_csrf_token()
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        secure=_SECURE_COOKIES,
        max_age=86400,
        samesite="strict",
        path="/",
    )
    _set_csrf_cookie(response, csrf_token)
    return {"success": True}

@app.post("/api/logout", response_class=JSONResponse)
async def api_logout(request: Request, response: Response):
    """Invalidate the current session."""
    _validate_csrf(request)
    token = request.cookies.get("session_token")
    if token:
        session_manager.invalidate(token)
    response.delete_cookie("session_token", path="/")
    response.delete_cookie(_CSRF_COOKIE, path="/")
    return {"success": True}

@app.post("/api/setup", response_class=JSONResponse)
async def api_setup(request: Request, response: Response):
    """Receive wizard data, write config.yaml, and issue a session cookie.

    LibreLinkUp credentials (``email`` / ``password``) are stored as-is under
    the ``librelinkup`` section so that the polling service can authenticate
    with the external API.

    Dashboard credentials are stored **separately** under ``dashboard_auth``:
    - ``username``: the dashboard login name (defaults to the LibreLinkUp email).
    - ``password_hash``: PBKDF2-HMAC-SHA256 hash of the dashboard password
      collected via the ``dashboard_password`` field.

    The two sets of credentials are **intentionally independent** — changing
    the LibreLinkUp password does not affect dashboard access and vice-versa.

    If the system is already configured, a valid session token is required to
    prevent unauthorised reconfiguration.
    """
    global _config

    # Block reconfiguration unless the caller is authenticated.
    if is_configured():
        token = request.cookies.get("session_token")
        if not session_manager.is_valid(token):
            raise HTTPException(
                status_code=403,
                detail="Ya configurado. Inicia sesión para reconfigurar.",
            )
        # Enforce CSRF for authenticated reconfiguration requests.
        _validate_csrf(request)
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON inválido")

    email = str(data.get("email", "")).strip()
    password = str(data.get("password", "")).strip()
    if not email or not password:
        raise HTTPException(
            status_code=422, detail="Email y contraseña son obligatorios"
        )

    # Dashboard credentials — separate from LibreLinkUp credentials.
    dashboard_password = str(data.get("dashboard_password", "")).strip()
    if not dashboard_password:
        raise HTTPException(
            status_code=422,
            detail="La contraseña del dashboard es obligatoria",
        )
    if len(dashboard_password) < 8:
        raise HTTPException(
            status_code=422,
            detail="La contraseña del panel de control debe tener al menos 8 caracteres.",
        )
    dashboard_username = str(data.get("dashboard_username", email)).strip() or email

    # Region selector — validated against the supported REGION_MAP keys.
    _VALID_REGIONS = {"US", "EU", "EU2", "DE", "FR", "JP", "AP", "AU", "AE", "CA", "LA", "RU"}
    region = str(data.get("region", "EU")).upper().strip()
    if region not in _VALID_REGIONS:
        raise HTTPException(status_code=422, detail=f"Región no válida: {region}")

    try:
        low_threshold = int(data.get("low_threshold", 70))
        high_threshold = int(data.get("high_threshold", 180))
        cooldown_minutes = int(data.get("cooldown_minutes", 30))
        max_reading_age_minutes = int(data.get("max_reading_age_minutes", 15))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Umbrales deben ser números")

    if low_threshold >= high_threshold:
        raise HTTPException(
            status_code=422,
            detail="El umbral bajo debe ser menor que el umbral alto",
        )

    # Build outputs list — validate required fields per output type.
    notification_type = data.get("notification_type", "none")
    outputs: list[dict] = []

    if notification_type == "telegram":
        bot_token = str(data.get("telegram_bot_token", "")).strip()
        chat_id = str(data.get("telegram_chat_id", "")).strip()
        if not bot_token or not chat_id:
            raise HTTPException(
                status_code=422,
                detail="Telegram requiere bot_token y chat_id",
            )
        outputs.append(
            {
                "type": "telegram",
                "enabled": True,
                "bot_token": bot_token,
                "chat_id": chat_id,
            }
        )
    elif notification_type == "webhook":
        webhook_url = str(data.get("webhook_url", "")).strip()
        if not webhook_url:
            raise HTTPException(
                status_code=422,
                detail="Webhook requiere url",
            )
        outputs.append(
            {
                "type": "webhook",
                "enabled": True,
                "url": webhook_url,
                "token": "",
                "device": "",
                "language": "es-MX",
            }
        )
    elif notification_type == "whatsapp":
        phone_number_id = str(data.get("whatsapp_phone_number_id", "")).strip()
        access_token = str(data.get("whatsapp_access_token", "")).strip()
        recipient = str(data.get("whatsapp_recipient", "")).strip()
        if not phone_number_id or not access_token or not recipient:
            raise HTTPException(
                status_code=422,
                detail="WhatsApp requiere phone_number_id, access_token y recipient",
            )
        outputs.append(
            {
                "type": "whatsapp",
                "enabled": True,
                "phone_number_id": phone_number_id,
                "access_token": access_token,
                "recipient": recipient,
                "template_name": "glucose_alert",
                "language_code": "es_MX",
            }
        )
    # When notification_type is "none", outputs remains empty and the
    # monitoring mode is set to "dashboard" so validation passes correctly.

    # Choose a sensible default mode: dashboard-only when no alerting output
    # is configured, cron otherwise.
    monitoring_mode = "cron" if outputs else "dashboard"

    config_dict = {
        "librelinkup": {
            "email": email,
            "password": encrypt_value(password),
            "region": region,
        },
        "dashboard_auth": {
            "username": dashboard_username,
            "password_hash": hash_password(dashboard_password),
        },
        "alerts": {
            "low_threshold": low_threshold,
            "high_threshold": high_threshold,
            "cooldown_minutes": cooldown_minutes,
            "max_reading_age_minutes": max_reading_age_minutes,
            "messages": {
                "low": "⚠️ {patient_name}: glucosa en {value} mg/dL {trend} — BAJA",
                "high": "⚠️ {patient_name}: glucosa en {value} mg/dL {trend} — ALTA",
            },
            "trend": {
                "enabled": True,
                "low_approaching_threshold": 100,
                "high_approaching_threshold": 150,
                "messages": {
                    "falling_fast": "🔻 {patient_name}: glucosa en {value} mg/dL {trend} — BAJANDO RÁPIDO",
                    "falling": "📉 {patient_name}: glucosa en {value} mg/dL {trend} — bajando, posible hipo",
                    "rising_fast": "🔺 {patient_name}: glucosa en {value} mg/dL {trend} — SUBIENDO RÁPIDO",
                    "rising": "📈 {patient_name}: glucosa en {value} mg/dL {trend} — subiendo, posible hiper",
                },
            },
        },
        "outputs": outputs,
        "monitoring": {
            "mode": monitoring_mode,
            "interval_seconds": 300,
        },
        "dashboard": {
            "enabled": True,
            "host": "0.0.0.0",
            "port": 8080,
        },
        "logging": {
            "level": "INFO",
            "file": "",
        },
        "state_file": "state.json",
        "lock_file": "/tmp/family-glucose-monitor.lock",
        "alert_history_db": "alert_history.db",
        "alert_history_max_days": 7,
    }

    # Validate the assembled config before writing it to disk.
    config_errors = schema_validate_config(config_dict)
    if config_errors:
        logger.warning("Setup produced invalid config (%d error(s)); not persisting", len(config_errors))
        raise HTTPException(
            status_code=422,
            detail={"message": "La configuración generada no es válida.", "errors": config_errors},
        )

    config_path = PROJECT_ROOT / "config.yaml"
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config_dict, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    # Restrict file permissions: owner read/write only (0600)
    try:
        os.chmod(config_path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError as e:
        logger.warning("Could not restrict config.yaml permissions: %s", e)

    # Reload internal config
    _config = config_dict

    token = session_manager.create_session()
    csrf_token = _generate_csrf_token()
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        secure=_SECURE_COOKIES,
        max_age=86400,
        samesite="strict",
        path="/",
    )
    _set_csrf_cookie(response, csrf_token)
    return {"success": True}