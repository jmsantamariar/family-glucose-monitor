"""Reusable connection testers for LibreLinkUp and Telegram.

These functions are shared between the settings UI (``/configuracion``) and
the CLI validation scripts (``validate_connection.py``,
``validate_telegram.py``).  They perform real network calls and return a
structured result dict — callers decide how to format the message.
"""
from __future__ import annotations

import logging
from typing import Any

import requests as _requests

logger = logging.getLogger(__name__)

# ── Region map ────────────────────────────────────────────────────────────────

try:
    from pylibrelinkup.api_url import APIUrl  # type: ignore[import-untyped]

    REGION_MAP: dict[str, Any] = {
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
except ImportError:  # pragma: no cover
    REGION_MAP = {}


# ── LibreLinkUp tester ────────────────────────────────────────────────────────

def test_librelinkup(email: str, password: str, region: str) -> dict:
    """Test LibreLinkUp credentials and return a structured result.

    Parameters
    ----------
    email:
        LibreLinkUp account email.
    password:
        Plaintext password (callers must decrypt before passing here).
    region:
        Region code such as ``"EU"`` or ``"US"``.

    Returns
    -------
    dict with keys:

    * ``ok`` (bool): Whether authentication succeeded.
    * ``message`` (str): Human-readable message in Spanish.
    * ``patients`` (list[dict]): Each item has ``name``, ``value``
      (int mg/dL), ``status`` (``"BAJA"`` / ``"ALTA"`` / ``"NORMAL"``).
      Empty list on failure.

    Secrets are never included in the returned dict or in log messages.
    """
    try:
        from pylibrelinkup import PyLibreLinkUp  # type: ignore[import-untyped]
        from pylibrelinkup.exceptions import RedirectError  # type: ignore[import-untyped]
    except ImportError:
        return {
            "ok": False,
            "message": "Librería pylibrelinkup no disponible.",
            "patients": [],
        }

    if not email or not password:
        return {
            "ok": False,
            "message": "Faltan campos obligatorios: email y contraseña.",
            "patients": [],
        }

    region_upper = region.upper().strip()
    api_url = REGION_MAP.get(region_upper)
    if api_url is None:
        return {
            "ok": False,
            "message": f"Región no válida: {region_upper}",
            "patients": [],
        }

    try:
        client = PyLibreLinkUp(email=email, password=password, api_url=api_url)
        try:
            client.authenticate()
        except RedirectError as redir:
            client = PyLibreLinkUp(email=email, password=password, api_url=redir.api_url)
            client.authenticate()
    except Exception as exc:
        exc_type = type(exc).__name__
        exc_msg = str(exc)
        # Avoid leaking credentials in the message
        safe_msg = exc_msg.replace(password, "***") if password else exc_msg
        logger.warning("LibreLinkUp test auth failed [%s]: %s", exc_type, safe_msg)
        if "credential" in exc_msg.lower() or "unauthorized" in exc_msg.lower() or "401" in exc_msg:
            return {
                "ok": False,
                "message": "Credenciales inválidas. Verifica email y contraseña.",
                "patients": [],
            }
        if "timeout" in exc_msg.lower():
            return {
                "ok": False,
                "message": "Error de red o timeout al conectar con LibreLinkUp.",
                "patients": [],
            }
        return {
            "ok": False,
            "message": f"No se pudo conectar con LibreLinkUp: {exc_type}",
            "patients": [],
        }

    # Fetch patients
    try:
        patients = client.get_patients()
    except Exception as exc:
        logger.warning("LibreLinkUp get_patients failed: %s", type(exc).__name__)
        return {
            "ok": False,
            "message": "Autenticación correcta pero no se pudieron obtener los pacientes.",
            "patients": [],
        }

    if not patients:
        return {
            "ok": True,
            "message": "Conexión exitosa con LibreLinkUp, pero no hay pacientes vinculados.",
            "patients": [],
        }

    patient_list: list[dict] = []
    for patient in patients:
        name = f"{patient.first_name} {patient.last_name}".strip()
        try:
            latest = client.latest(patient)
            if latest is None:
                patient_list.append({"name": name, "value": None, "status": "SIN DATOS"})
                continue
            value = int(latest.value)
            if latest.is_low:
                status = "BAJA"
            elif latest.is_high:
                status = "ALTA"
            else:
                status = "NORMAL"
            patient_list.append({"name": name, "value": value, "status": status})
        except Exception as exc:
            logger.warning("LibreLinkUp latest() failed for %s: %s", name, type(exc).__name__)
            patient_list.append({"name": name, "value": None, "status": "ERROR"})

    return {
        "ok": True,
        "message": "Conexión exitosa con LibreLinkUp.",
        "patients": patient_list,
    }


# ── Telegram tester ───────────────────────────────────────────────────────────

_TELEGRAM_API = "https://api.telegram.org"


def test_telegram(bot_token: str, chat_id: str) -> dict:
    """Test Telegram bot configuration by sending a test message.

    Parameters
    ----------
    bot_token:
        Telegram bot API token.
    chat_id:
        Target chat / group ID.

    Returns
    -------
    dict with keys:

    * ``ok`` (bool): Whether the test message was sent.
    * ``message`` (str): Human-readable message in Spanish.

    Secrets are never included in the returned dict or in log messages.
    """
    if not bot_token or not chat_id:
        return {
            "ok": False,
            "message": "Faltan campos obligatorios: bot token y chat ID.",
        }

    test_text = "✅ <b>Family Glucose Monitor</b> — Telegram configurado correctamente."
    url = f"{_TELEGRAM_API}/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": test_text, "parse_mode": "HTML"}

    try:
        resp = _requests.post(url, json=payload, timeout=10)
    except _requests.exceptions.Timeout:
        return {"ok": False, "message": "Timeout al conectar con Telegram."}
    except _requests.exceptions.ConnectionError:
        return {"ok": False, "message": "Error de red al conectar con Telegram."}
    except _requests.RequestException as exc:
        logger.warning("Telegram test request failed: %s", type(exc).__name__)
        return {"ok": False, "message": "No se pudo enviar mensaje de prueba a Telegram."}

    if resp.status_code == 401:
        return {"ok": False, "message": "Token de bot inválido."}

    if resp.status_code == 400:
        # Bad Request often means invalid chat_id or parse mode issues
        try:
            detail = resp.json().get("description", "")
        except Exception:
            detail = ""
        if "chat not found" in detail.lower():
            return {"ok": False, "message": "Chat ID inválido o bot no tiene acceso a ese chat."}
        return {"ok": False, "message": f"Error de Telegram (400): {detail or 'parámetros inválidos'}"}

    if not resp.ok:
        try:
            detail = resp.json().get("description", "")
        except Exception:
            detail = ""
        logger.warning("Telegram test returned %d: %s", resp.status_code, detail)
        return {
            "ok": False,
            "message": f"No se pudo enviar mensaje de prueba a Telegram (código {resp.status_code}).",
        }

    return {"ok": True, "message": "Telegram configurado correctamente."}
