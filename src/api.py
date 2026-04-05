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

import requests as _requests
import yaml
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi import Query

from src import alert_engine
from src.alert_history import get_alerts
from src.auth import hash_password, is_configured, session_manager, verify_credentials
from src.bootstrap import check_config_writable
from src.config_schema import validate_config as schema_validate_config
from src.connection_tester import test_librelinkup as _test_librelinkup
from src.connection_tester import test_telegram as _test_telegram
from src.crypto import decrypt_value, encrypt_value, is_encrypted
from src.outputs.webpush import WebPushOutput, get_vapid_public_key
from src.paths import get_cache_path, get_reading_history_db_path
import src.push_subscriptions as _push_subs
from src import reading_history as _reading_history
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

    # Initialise push-subscription database.
    _push_subs_db = str(PROJECT_ROOT / "push_subscriptions.db")
    try:
        _push_subs.init_db(_push_subs_db)
    except Exception as exc:
        logger.warning("Could not initialise push subscriptions DB: %s", exc)

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

    # Pre-populate the in-memory cache from any existing cache file so that
    # the dashboard shows data immediately on first request without requiring
    # a manual navigation or waiting for the first polling cycle to complete.
    # _last_mtime is 0.0 at startup so this always loads the file if it exists.
    try:
        _load_and_enrich_cache()
    except Exception as exc:
        logger.warning("Could not pre-load readings cache at startup: %s", exc)

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
    "/manifest.json",
    "/sw.js",
    "/api/push/vapid-public-key",
}

_AUTH_EXEMPT_PREFIXES = (
    "/icons/",
)

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Enforce session authentication on all protected routes."""
    if _ALLOW_AUTH_DISABLED:
        return await call_next(request)

    if request.url.path in _AUTH_EXEMPT_PATHS:
        return await call_next(request)

    if request.url.path.startswith(_AUTH_EXEMPT_PREFIXES):
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
    return get_cache_path(_config)


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

    # Persist readings to history DB for sparkline time-series (best-effort).
    if new_cache:
        try:
            rh_path = get_reading_history_db_path(_config)
            _reading_history.init_db(rh_path)
            readings_to_log = []
            for r in new_cache.values():
                pid = r.get("patient_id", "")
                pname = r.get("patient_name", pid)
                gval = r.get("glucose_value") or r.get("value", 0)
                if pid and gval:
                    readings_to_log.append((pid, pname, int(gval)))
            if readings_to_log:
                _reading_history.log_readings(rh_path, readings_to_log)
        except Exception as exc:
            logger.warning("Failed to persist readings to history DB: %s", exc)


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


@app.get("/api/patients/{patient_id}/history", response_class=JSONResponse)
def get_patient_history(patient_id: str, hours: int = Query(default=3, ge=1, le=24)):
    """Return recent glucose readings for *patient_id* within the last *hours* hours.

    Readings are sampled at each polling cycle (~5 min) and stored in
    ``reading_history.db``.  Returns an empty list when no history exists yet.
    Unlike ``/api/alerts``, this endpoint returns **all** readings, not just
    those that triggered an alert, making it suitable for sparkline visualisation.
    """
    rh_path = get_reading_history_db_path(_config)
    readings = _reading_history.get_readings(rh_path, patient_id=patient_id, hours=hours)
    return readings

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

# ── PWA static assets ────────────────────────────────────────────────────────

_DASHBOARD_DIR = Path(__file__).parent / "dashboard"

_MIME_TYPES: dict[str, str] = {
    ".json": "application/json",
    ".js":   "application/javascript",
    ".svg":  "image/svg+xml",
    ".png":  "image/png",
    ".ico":  "image/x-icon",
}


@app.get("/manifest.json")
def pwa_manifest():
    """Serve the Web App Manifest so browsers can offer 'Add to Home Screen'."""
    path = _DASHBOARD_DIR / "manifest.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="manifest.json not found")
    return FileResponse(path, media_type="application/manifest+json")


@app.get("/sw.js")
def pwa_service_worker():
    """Serve the PWA service worker script."""
    path = _DASHBOARD_DIR / "sw.js"
    if not path.exists():
        raise HTTPException(status_code=404, detail="sw.js not found")
    return FileResponse(path, media_type="application/javascript")


@app.get("/icons/{filename}")
def pwa_icon(filename: str):
    """Serve PWA icon assets from the dashboard/icons/ directory."""
    icons_dir = _DASHBOARD_DIR / "icons"
    # Prevent path traversal: reject any filename containing path separators.
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid icon filename")
    path = (icons_dir / filename).resolve()
    # Double-check that the resolved path is still inside icons_dir.
    try:
        path.relative_to(icons_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid icon filename")
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Icon '{filename}' not found")
    suffix = path.suffix.lower()
    media_type = _MIME_TYPES.get(suffix, "application/octet-stream")
    return FileResponse(path, media_type=media_type)


# ── Web Push notification endpoints ──────────────────────────────────────────

@app.get("/api/push/vapid-public-key", response_class=JSONResponse)
def push_vapid_public_key():
    """Return the VAPID public key so browsers can subscribe to push notifications.

    This endpoint is auth-exempt because the public key must be available
    before the user logs in (e.g., from the login page).
    """
    try:
        key = get_vapid_public_key()
    except Exception as exc:
        logger.error("Could not load VAPID public key: %s", exc)
        raise HTTPException(status_code=500, detail="VAPID keys unavailable")
    return {"publicKey": key}


@app.post("/api/push/subscribe", response_class=JSONResponse)
async def push_subscribe(request: Request):
    """Save a browser push subscription from an authenticated user.

    Expects a JSON body matching the ``PushSubscription.toJSON()`` output::

        {
            "endpoint": "https://...",
            "keys": {
                "p256dh": "<base64url>",
                "auth":   "<base64url>"
            }
        }
    """
    _validate_csrf(request)
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON inválido")

    endpoint = str(data.get("endpoint", "")).strip()
    keys = data.get("keys") or {}
    p256dh = str(keys.get("p256dh", "")).strip()
    auth = str(keys.get("auth", "")).strip()

    if not endpoint or not p256dh or not auth:
        raise HTTPException(
            status_code=422,
            detail="endpoint, keys.p256dh y keys.auth son obligatorios",
        )

    try:
        _push_subs.save_subscription(endpoint, p256dh, auth)
    except Exception as exc:
        logger.error("Failed to save push subscription: %s", exc)
        raise HTTPException(status_code=500, detail="No se pudo guardar la suscripción")

    return {"message": "✅ Suscripción guardada"}


@app.post("/api/push/unsubscribe", response_class=JSONResponse)
async def push_unsubscribe(request: Request):
    """Remove a browser push subscription.

    Expects a JSON body with ``{"endpoint": "<url>"}``.
    """
    _validate_csrf(request)
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON inválido")

    endpoint = str(data.get("endpoint", "")).strip()
    if not endpoint:
        raise HTTPException(status_code=422, detail="endpoint es obligatorio")

    try:
        _push_subs.delete_subscription(endpoint)
    except Exception as exc:
        logger.error("Failed to delete push subscription: %s", exc)
        raise HTTPException(status_code=500, detail="No se pudo eliminar la suscripción")

    return {"message": "✅ Suscripción eliminada"}



@app.get("/api/setup/status", response_class=JSONResponse)
def setup_status():
    """Return whether the system has already been configured."""
    return {"configured": is_setup_complete()}


_TELEGRAM_API_URL = "https://api.telegram.org"


@app.post("/api/setup/telegram/fetch-chat-id", response_class=JSONResponse)
async def api_telegram_fetch_chat_id(request: Request):
    """Call Telegram's getUpdates to discover chat IDs from recent messages.

    This endpoint is used by the setup wizard to help non-technical users
    retrieve their ``chat_id`` without having to call the Telegram Bot API
    manually.  The caller provides the bot token; the endpoint forwards it to
    ``getUpdates`` and returns the unique chat IDs found in the response.

    The user must have sent at least one message to the bot before calling
    this endpoint so that Telegram has a pending update to return.
    """
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON inválido")

    bot_token = str(data.get("bot_token", "")).strip()
    if not bot_token:
        raise HTTPException(status_code=422, detail="bot_token es requerido")

    url = f"{_TELEGRAM_API_URL}/bot{bot_token}/getUpdates"
    try:
        resp = _requests.get(url, timeout=10)
    except _requests.RequestException:
        raise HTTPException(
            status_code=502,
            detail="Error al contactar Telegram.",
        )

    if resp.status_code == 401:
        raise HTTPException(
            status_code=422,
            detail="Token inválido. Verifica el token del bot.",
        )
    if not resp.ok:
        raise HTTPException(
            status_code=502,
            detail=f"Error de Telegram: {resp.status_code}",
        )

    try:
        result = resp.json()
    except (ValueError, json.JSONDecodeError):
        raise HTTPException(
            status_code=502,
            detail="Respuesta inválida de Telegram.",
        )

    if not isinstance(result, dict) or result.get("ok") is not True:
        error_code = result.get("error_code") if isinstance(result, dict) else None
        description = result.get("description") if isinstance(result, dict) else None
        if error_code == 401:
            raise HTTPException(
                status_code=422,
                detail="Token inválido. Verifica el token del bot.",
            )
        raise HTTPException(
            status_code=502,
            detail=description or "Error de Telegram.",
        )
    updates = result.get("result", [])

    # Extract unique chats from all update types that carry a chat object.
    seen: dict[str, str] = {}
    for update in updates:
        for key in ("message", "channel_post", "edited_message", "edited_channel_post"):
            msg = update.get(key)
            if not msg:
                continue
            chat = msg.get("chat", {})
            chat_id = chat.get("id")
            if chat_id is None:
                continue
            chat_id_str = str(chat_id)
            if chat_id_str not in seen:
                name = (
                    chat.get("title")
                    or chat.get("username")
                    or chat.get("first_name")
                    or chat_id_str
                )
                seen[chat_id_str] = name

    return {"chats": [{"id": cid, "name": name} for cid, name in seen.items()]}


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

    # Guard: fail early with a clear message if config.yaml is read-only.
    writable_error = check_config_writable(config_path)
    if writable_error:
        raise HTTPException(status_code=500, detail=writable_error)

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

# ── Settings (Configuración) routes ──────────────────────────────────────────

@app.get("/configuracion", response_class=HTMLResponse)
def configuracion_page():
    """Serve the settings page. Requires authentication (handled by middleware)."""
    html_path = Path(__file__).parent / "dashboard" / "configuracion.html"
    if not html_path.exists():
        raise HTTPException(status_code=500, detail="Configuración HTML no encontrado")
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@app.get("/api/configuracion", response_class=JSONResponse)
def api_get_configuracion():
    """Return current configuration for the settings page.

    Secrets (LibreLinkUp password, Telegram bot token) are NEVER returned
    in plaintext.  A boolean flag indicates whether each secret is set.
    """
    ll = _config.get("librelinkup", {})
    alerts_cfg = _config.get("alerts", {})
    outputs = _config.get("outputs", [])

    telegram_cfg = next((o for o in outputs if o.get("type") == "telegram"), {})
    has_bot_token = bool(str(telegram_cfg.get("bot_token", "")).strip())

    return {
        "librelinkup": {
            "email": str(ll.get("email", "")),
            "has_password": bool(str(ll.get("password", "")).strip()),
            "region": str(ll.get("region", "EU")),
        },
        "alerts": {
            "low_threshold": alerts_cfg.get("low_threshold", 70),
            "high_threshold": alerts_cfg.get("high_threshold", 180),
            "cooldown_minutes": alerts_cfg.get("cooldown_minutes", 30),
            "max_reading_age_minutes": alerts_cfg.get("max_reading_age_minutes", 15),
        },
        "telegram": {
            "enabled": bool(telegram_cfg.get("enabled", False)),
            "has_bot_token": has_bot_token,
            "chat_id": str(telegram_cfg.get("chat_id", "")),
        },
    }


@app.post("/api/configuracion", response_class=JSONResponse)
async def api_save_configuracion(request: Request):
    """Persist updated settings from the settings page.

    Secret fields are only overwritten when the caller supplies a non-empty
    value.  An empty value means keep the existing secret.
    """
    global _config

    _validate_csrf(request)

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON inválido")

    if not _config:
        raise HTTPException(
            status_code=409,
            detail="No hay configuración guardada. Usa el asistente de configuración inicial.",
        )

    import copy
    new_config = copy.deepcopy(_config)

    # LibreLinkUp section
    ll = new_config.setdefault("librelinkup", {})
    email = str(data.get("librelinkup_email", "")).strip()
    if email:
        ll["email"] = email
    new_password = str(data.get("librelinkup_password", "")).strip()
    if new_password:
        ll["password"] = encrypt_value(new_password)
    region = str(data.get("librelinkup_region", "")).upper().strip()
    _VALID_REGIONS = {"US", "EU", "EU2", "DE", "FR", "JP", "AP", "AU", "AE", "CA", "LA", "RU"}
    if region:
        if region not in _VALID_REGIONS:
            raise HTTPException(status_code=422, detail=f"Región no válida: {region}")
        ll["region"] = region

    # Alerts section
    alerts_cfg = new_config.setdefault("alerts", {})
    for field in ("low_threshold", "high_threshold", "cooldown_minutes", "max_reading_age_minutes"):
        raw = data.get(field)
        if raw is not None:
            try:
                alerts_cfg[field] = int(raw)
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=422, detail=f"{field} debe ser un número entero"
                )

    low = alerts_cfg.get("low_threshold", 0)
    high = alerts_cfg.get("high_threshold", 0)
    if isinstance(low, (int, float)) and isinstance(high, (int, float)) and low >= high:
        raise HTTPException(
            status_code=422,
            detail="El umbral bajo debe ser menor que el umbral alto",
        )

    # Telegram section
    outputs: list[dict] = new_config.setdefault("outputs", [])
    telegram_enabled = data.get("telegram_enabled")
    telegram_chat_id = str(data.get("telegram_chat_id", "")).strip()
    new_bot_token = str(data.get("telegram_bot_token", "")).strip()

    if telegram_enabled is not None:
        tg_entry = next((o for o in outputs if o.get("type") == "telegram"), None)
        if tg_entry is None:
            tg_entry = {"type": "telegram", "enabled": False, "bot_token": "", "chat_id": ""}
            outputs.append(tg_entry)

        tg_entry["enabled"] = bool(telegram_enabled)
        if new_bot_token:
            tg_entry["bot_token"] = new_bot_token
        if telegram_chat_id:
            tg_entry["chat_id"] = telegram_chat_id

        if tg_entry["enabled"]:
            if not str(tg_entry.get("bot_token", "")).strip():
                raise HTTPException(
                    status_code=422,
                    detail="Telegram activo requiere un bot token",
                )
            if not str(tg_entry.get("chat_id", "")).strip():
                raise HTTPException(
                    status_code=422,
                    detail="Telegram activo requiere un chat ID",
                )

    config_errors = schema_validate_config(new_config)
    if config_errors:
        logger.warning("Settings update produced invalid config (%d error(s))", len(config_errors))
        raise HTTPException(
            status_code=422,
            detail={"message": "La configuración no es válida.", "errors": config_errors},
        )

    config_path = PROJECT_ROOT / "config.yaml"
    writable_error = check_config_writable(config_path)
    if writable_error:
        raise HTTPException(status_code=500, detail=writable_error)

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(new_config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    try:
        os.chmod(config_path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError as exc:
        logger.warning("Could not restrict config.yaml permissions: %s", exc)

    _config = new_config

    return {
        "success": True,
        "message": "Configuración guardada correctamente.",
        "applied_hot": True,
        "note": (
            "Los cambios en umbrales se aplican de inmediato. "
            "Los cambios en LibreLinkUp se usarán en el próximo ciclo de polling. "
            "Los cambios en Telegram se usarán en la próxima alerta enviada."
        ),
    }


@app.post("/api/configuracion/probar-librelinkup", response_class=JSONResponse)
async def api_probar_librelinkup(request: Request):
    """Test LibreLinkUp connection using values from the request.

    Uses form values (approach A): if a field is empty, falls back to the
    saved config value.  Never persists any credentials.
    """
    _validate_csrf(request)
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON inválido")

    email = str(data.get("email", "")).strip()
    password_input = str(data.get("password", "")).strip()
    region = str(data.get("region", "")).strip()

    ll = _config.get("librelinkup", {})
    if not email:
        email = str(ll.get("email", "")).strip()
    if not password_input:
        raw_pw = str(ll.get("password", "")).strip()
        try:
            password_input = decrypt_value(raw_pw)
        except Exception:
            password_input = raw_pw
    if not region:
        region = str(ll.get("region", "EU")).strip()

    if not email or not password_input:
        raise HTTPException(status_code=422, detail="Faltan campos obligatorios")

    return _test_librelinkup(email, password_input, region)


@app.post("/api/configuracion/probar-telegram", response_class=JSONResponse)
async def api_probar_telegram(request: Request):
    """Test Telegram bot configuration using values from the request.

    Uses form values (approach A): if a field is empty, falls back to the
    saved config value.  Never persists any credentials.
    """
    _validate_csrf(request)
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON inválido")

    bot_token_input = str(data.get("bot_token", "")).strip()
    chat_id = str(data.get("chat_id", "")).strip()

    outputs = _config.get("outputs", [])
    tg_cfg = next((o for o in outputs if o.get("type") == "telegram"), {})
    if not bot_token_input:
        bot_token_input = str(tg_cfg.get("bot_token", "")).strip()
    if not chat_id:
        chat_id = str(tg_cfg.get("chat_id", "")).strip()

    if not bot_token_input or not chat_id:
        raise HTTPException(
            status_code=422,
            detail="Faltan campos obligatorios: bot token y chat ID",
        )

    return _test_telegram(bot_token_input, chat_id)
