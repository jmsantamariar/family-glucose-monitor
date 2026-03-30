"""Telegram Bot API output implementation for alert dispatch."""
import logging
import requests
from src.outputs.base import BaseOutput

logger = logging.getLogger(__name__)
TELEGRAM_API = "https://api.telegram.org"


class TelegramOutput(BaseOutput):
    def __init__(self, bot_token: str, chat_id: str) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id

    def send_alert(self, message: str, glucose_value: int, level: str) -> bool:
        url = f"{TELEGRAM_API}/bot{self.bot_token}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": message, "parse_mode": "HTML"}
        logger.debug("Telegram sendMessage to chat_id %s", self.chat_id)
        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.ok:
                logger.info("Telegram message sent to %s", self.chat_id)
                return True
            logger.error("Telegram API error %d: %s", resp.status_code, resp.text[:200])
            return False
        except requests.RequestException as e:
            logger.error("Telegram request failed: %s", e)
            return False
