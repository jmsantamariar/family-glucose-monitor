"""FastAPI web server for the authenticated glucose monitoring dashboard.

This is the **internal** authenticated application.  All routes (except the
setup wizard and login pages) require a valid session cookie.

Responsibilities
----------------
* Serve the dashboard UI (``/``, ``/login``, ``/setup``).
* Handle authentication: setup wizard, login, logout.
* Maintain an in-memory cache of the latest patient readings updated by a
  background polling thread.
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
``timestamp``).  The two modules are **intentionally separate**.
"""
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from src import alert_engine
from src.alert_history import get_alerts
from src.auth import hash_password, is_configured, session_manager, verify_credentials
from src.glucose_reader import read_all_patients

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# In-memory cache of latest readings per patient
_readings_cache: dict = {}
_cache_lock = threading.Lock()
_config: dict = {}

APP_ENV = os.environ.get("APP_ENV") or os.environ.get("ENV") or "dev"
_ALLOW_AUTH_DISABLED = (
    os.environ.get("AUTH_DISABLED") == "1"
    and APP_ENV.lower() in {"dev", "development", "local", "test"}
)
if os.environ.get("AUTH_DISABLED") == "1" and not _ALLOW_AUTH_DISABLED:
    logger.warning(
        "AUTH_DISABLED=1 ignorado porque APP_ENV/ENV=%s no es un entorno de desarrollo",
        APP_ENV,
    )

def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)

@asynccontextmanager
async def lifespan(application: "FastAPI"):
    global _config
    try:
        _config = load_config()
    except FileNotFoundError:
        logger.warning("config.yaml not found, dashboard will start without polling")
    else:
        interval = _config.get("monitoring", {}).get("interval_seconds", 300)
        thread = threading.Thread(target=_poll_loop, args=(interval,), daemon=True)
        thread.start()
        logger.info("Background polling started every %d seconds", interval)
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

    if is_configured():
        return RedirectResponse(url="/login", status_code=302)
    return RedirectResponse(url="/setup", status_code=302)

def _poll_loop(interval: int):
    """Background thread that polls LibreLinkUp and updates the cache.

    The in-memory cache is **replaced atomically** on every cycle so that
    patients who are no longer returned by the API are removed immediately
    instead of remaining as stale ghost entries.
    """
    while True:
        try:
            readings = read_all_patients(_config)
            new_cache: dict = {}
            for r in readings:
                pid = r["patient_id"]
                glucose = r["value"]
                trend_arrow = r.get("trend_arrow", "")
                level = alert_engine.evaluate(glucose, _config)
                trend_alert = alert_engine.evaluate_trend(glucose, trend_arrow, _config)
                r["glucose_value"] = glucose
                r["level"] = level
                r["trend_alert"] = trend_alert
                r["color"] = _get_color(level, trend_alert)
                r["fetched_at"] = datetime.now(timezone.utc).isoformat()
                new_cache[pid] = r
            with _cache_lock:
                _readings_cache.clear()
                _readings_cache.update(new_cache)
            logger.info("Polled %d patients successfully", len(readings))
        except Exception as e:
            logger.error("Polling error: %s", e)
        time.sleep(interval)


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
    with _cache_lock:
        patients = list(_readings_cache.values())
    return {"patients": patients, "count": len(patients)}

@app.get("/api/patients/{patient_id}", response_class=JSONResponse)
def get_patient(patient_id: str):
    """Return a specific patient's latest reading."""
    with _cache_lock:
        reading = _readings_cache.get(patient_id)
    if not reading:
        raise HTTPException(status_code=404, detail="Patient not found")
    return reading

@app.get("/api/health", response_class=JSONResponse)
def health_check():
    """Health check endpoint."""
    with _cache_lock:
        patient_count = len(_readings_cache)
    return {
        "status": "ok",
        "patients_monitored": patient_count,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

@app.get("/api/alerts", response_class=JSONResponse)
def get_alert_history(patient_id: Optional[str] = None, hours: int = 24):
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
    return {"configured": is_configured()}

@app.post("/api/login", response_class=JSONResponse)
async def api_login(request: Request, response: Response):
    """Validate credentials against dashboard_auth in config.yaml and issue a session cookie.

    Accepts ``username`` (or the legacy ``email`` field as an alias) and
    ``password``.  Credentials are verified against the ``dashboard_auth``
    section — **not** the LibreLinkUp credentials.
    """
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON inválido")

    # Accept both "username" and legacy "email" field
    username = str(data.get("username") or data.get("email", ""))
    password = str(data.get("password", ""))

    if not verify_credentials(username, password):
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")

    token = session_manager.create_session()
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        max_age=86400,
        samesite="lax",
    )
    return {"success": True}

@app.post("/api/logout", response_class=JSONResponse)
async def api_logout(request: Request, response: Response):
    """Invalidate the current session."""
    token = request.cookies.get("session_token")
    if token:
        session_manager.invalidate(token)
    response.delete_cookie("session_token")
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
    """
    global _config
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
    dashboard_username = str(data.get("dashboard_username", email)).strip() or email

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

    # Build outputs list
    notification_type = data.get("notification_type", "none")
    outputs: list[dict] = []

    if notification_type == "telegram":
        outputs.append(
            {
                "type": "telegram",
                "enabled": True,
                "bot_token": str(data.get("telegram_bot_token", "")),
                "chat_id": str(data.get("telegram_chat_id", "")),
            }
        )
    elif notification_type == "webhook":
        outputs.append(
            {
                "type": "webhook",
                "enabled": True,
                "url": str(data.get("webhook_url", "")),
                "token": "",
                "device": "",
                "language": "es-MX",
            }
        )
    elif notification_type == "whatsapp":
        outputs.append(
            {
                "type": "whatsapp",
                "enabled": True,
                "phone_number_id": str(data.get("whatsapp_phone_number_id", "")),
                "access_token": str(data.get("whatsapp_access_token", "")),
                "recipient": str(data.get("whatsapp_recipient", "")),
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
            "password": password,
            "region": "EU",
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

    config_path = PROJECT_ROOT / "config.yaml"
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config_dict, f, allow_unicode=True, default_flow_style=False)

    # Reload internal config
    _config = config_dict

    token = session_manager.create_session()
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        max_age=86400,
        samesite="lax",
    )
    return {"success": True}
