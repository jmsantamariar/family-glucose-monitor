"""Output channel registry and factory for alert delivery."""
import logging
import os

from src.outputs.base import BaseOutput
from src.outputs.telegram import TelegramOutput
from src.outputs.webhook import WebhookOutput
from src.outputs.webpush import WebPushOutput
from src.outputs.whatsapp import WhatsAppOutput

logger = logging.getLogger(__name__)


def build_outputs(config: dict) -> list[BaseOutput]:
    """Instantiate and return all enabled output channels from *config*.

    Always includes a :class:`~src.outputs.webpush.WebPushOutput` so that
    glucose alerts are delivered to every browser that subscribed to push
    notifications through the dashboard — even when no other channel is
    configured.
    """
    outputs: list[BaseOutput] = []
    for out_cfg in config.get("outputs", []):
        if not out_cfg.get("enabled", False):
            continue
        out_type = out_cfg.get("type")
        if out_type == "webhook":
            outputs.append(WebhookOutput(
                url=out_cfg["url"],
                token=out_cfg.get("token", ""),
                device=out_cfg.get("device", ""),
                language=out_cfg.get("language", ""),
            ))
        elif out_type == "whatsapp":
            access_token = os.environ.get("WHATSAPP_ACCESS_TOKEN") or out_cfg.get("access_token", "")
            outputs.append(WhatsAppOutput(
                phone_number_id=out_cfg["phone_number_id"],
                access_token=access_token,
                recipient=out_cfg["recipient"],
                template_name=out_cfg.get("template_name", "glucose_alert"),
                language_code=out_cfg.get("language_code", "es_MX"),
            ))
        elif out_type == "telegram":
            # Accept legacy "token" key from configs written before the field
            # was renamed to "bot_token" (bug fixed in wizard April 2026).
            bot_token = out_cfg.get("bot_token") or out_cfg.get("token", "")
            outputs.append(TelegramOutput(
                bot_token=bot_token,
                chat_id=out_cfg["chat_id"],
            ))
        else:
            logger.warning("Unknown output type '%s', skipping", out_type)

    # Always include the web-push channel.  When no browsers have subscribed
    # it sends nothing; subscriptions are managed at runtime via the dashboard.
    outputs.append(WebPushOutput())
    return outputs
