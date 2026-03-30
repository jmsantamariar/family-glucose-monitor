"""Webhook output implementation for alert dispatch."""
import logging
import requests
from src.outputs.base import BaseOutput

logger = logging.getLogger(__name__)


class WebhookOutput(BaseOutput):
    def __init__(self, url: str, token: str, device: str, language: str = "") -> None:
        self.url = url
        self.token = token
        self.device = device
        self.language = language

    def send_alert(self, message: str, glucose_value: int, level: str) -> bool:
        payload = {"token": self.token, "device": self.device, "text": message}
        if self.language:
            payload["language"] = self.language
        logger.debug("Webhook POST to %s with device: %s", self.url, self.device)
        try:
            resp = requests.post(self.url, json=payload, timeout=10)
            logger.info("Webhook response: %d %s", resp.status_code, resp.text[:200])
            return resp.ok
        except requests.RequestException as e:
            logger.error("Webhook request failed: %s", e)
            return False
