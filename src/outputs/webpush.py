"""Web Push (browser push notification) output for glucose alerts.

This adapter implements :class:`~src.outputs.base.BaseOutput` and delivers
alert messages as browser push notifications to every device that has
subscribed via the dashboard's "Enable push notifications" button.

VAPID keys
----------
VAPID authentication is required by all modern push services.  Keys are
loaded in this priority order:

1. ``VAPID_PRIVATE_KEY`` / ``VAPID_PUBLIC_KEY`` environment variables
   (PEM and base64url-encoded uncompressed public key, respectively).
2. The ``vapid_private.pem`` file adjacent to ``config.yaml`` in the
   project root.  If the file does not exist it is auto-generated on first
   use and the derived public key is logged at INFO level so operators can
   wire it into the frontend.

The public key must match the ``applicationServerKey`` constant in the
dashboard's JavaScript (``index.html``).  The ``/api/push/vapid-public-key``
endpoint serves it dynamically so clients always use the correct value.

Threading
---------
Notifications are sent synchronously from the caller's thread.  Failures
for individual subscriptions are caught and logged; expired/invalid
subscriptions (HTTP 404 / 410 from the push service) are automatically
removed from the database.
"""
import json
import logging
import os
from pathlib import Path

from pywebpush import WebPushException, webpush
from py_vapid import Vapid
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
import base64

import src.push_subscriptions as _subs
from src.outputs.base import BaseOutput

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_VAPID_PEM_FILE = _PROJECT_ROOT / "vapid_private.pem"

# Module-level cache of the loaded/generated Vapid instance and public key.
_vapid: Vapid | None = None
_public_key_b64: str | None = None


def _load_or_generate_vapid() -> tuple[Vapid, str]:
    """Return ``(vapid_instance, public_key_base64url)``.

    Keys are loaded from env vars or the PEM file; generated and saved when
    neither source is available.
    """
    global _vapid, _public_key_b64
    if _vapid is not None and _public_key_b64 is not None:
        return _vapid, _public_key_b64

    priv_pem_env = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    if priv_pem_env:
        _vapid = Vapid.from_pem(priv_pem_env.encode())
        logger.debug("VAPID private key loaded from VAPID_PRIVATE_KEY env var")
    elif _VAPID_PEM_FILE.exists():
        _vapid = Vapid.from_pem(_VAPID_PEM_FILE.read_bytes())
        logger.debug("VAPID private key loaded from %s", _VAPID_PEM_FILE)
    else:
        logger.info("No VAPID keys found — generating new key pair")
        _vapid = Vapid()
        _vapid.generate_keys()
        priv_bytes = _vapid.private_key.private_bytes(
            Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()
        )
        _VAPID_PEM_FILE.write_bytes(priv_bytes)
        _VAPID_PEM_FILE.chmod(0o600)
        logger.info("New VAPID key pair saved to %s", _VAPID_PEM_FILE)

    raw = _vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    _public_key_b64 = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    logger.info("VAPID public key (applicationServerKey): %s", _public_key_b64)
    return _vapid, _public_key_b64


def get_vapid_public_key() -> str:
    """Return the VAPID public key as an unpadded base64url string.

    This is the value that the browser uses as ``applicationServerKey`` when
    calling ``pushManager.subscribe()``.
    """
    _, pub = _load_or_generate_vapid()
    return pub


class WebPushOutput(BaseOutput):
    """Deliver glucose alert messages as browser push notifications.

    Parameters
    ----------
    vapid_subject:
        A ``mailto:`` or ``https://`` URI identifying the push service
        operator.  Required by the Web Push protocol.  Defaults to
        ``mailto:admin@localhost``.
    icon_url:
        Optional URL of the notification icon shown by the browser.
    """

    def __init__(
        self,
        vapid_subject: str = "mailto:admin@localhost",
        icon_url: str = "/icons/icon-192.svg",
    ) -> None:
        self._vapid_subject = vapid_subject
        self._icon_url = icon_url

    # ------------------------------------------------------------------
    # BaseOutput protocol
    # ------------------------------------------------------------------

    def send_alert(self, message: str, glucose_value: int, level: str) -> bool:
        """Send a push notification to all subscribed browsers.

        :returns: ``True`` if at least one notification was delivered.
        """
        subscriptions = _subs.get_all_subscriptions()
        if not subscriptions:
            logger.debug("WebPushOutput: no subscriptions, nothing to send")
            return False

        vapid_instance, _ = _load_or_generate_vapid()

        payload = json.dumps(
            {
                "title": _title_for_level(level),
                "body": message,
                "icon": self._icon_url,
                "glucose": glucose_value,
                "level": level,
            }
        )

        any_success = False
        stale_endpoints: list[str] = []

        for sub in subscriptions:
            sub_info = {
                "endpoint": sub["endpoint"],
                "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
            }
            try:
                webpush(
                    subscription_info=sub_info,
                    data=payload,
                    vapid_private_key=vapid_instance,
                    vapid_claims={"sub": self._vapid_subject},
                    timeout=10,
                )
                any_success = True
                logger.debug("Push sent to %s…", sub["endpoint"][:40])
            except WebPushException as exc:
                status = getattr(exc.response, "status_code", None) if exc.response else None
                if status in (404, 410):
                    logger.info(
                        "Push subscription expired (HTTP %s), scheduling removal: %s…",
                        status,
                        sub["endpoint"][:40],
                    )
                    stale_endpoints.append(sub["endpoint"])
                else:
                    logger.error(
                        "WebPush failed for %s…: %s", sub["endpoint"][:40], exc
                    )
            except Exception as exc:
                logger.error(
                    "WebPush unexpected error for %s…: %s", sub["endpoint"][:40], exc
                )

        for endpoint in stale_endpoints:
            _subs.delete_subscription(endpoint)

        return any_success


def _title_for_level(level: str) -> str:
    """Return a human-readable notification title for the given alert level."""
    mapping = {
        "low": "🩸 Glucosa baja",
        "high": "⚠️ Glucosa alta",
        "normal": "✅ Glucosa normal",
        "low_approaching": "📉 Glucosa bajando",
        "high_approaching": "📈 Glucosa subiendo",
    }
    return mapping.get(level, "🔔 Alerta de glucosa")
