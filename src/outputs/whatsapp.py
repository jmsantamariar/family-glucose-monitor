"""WhatsApp Cloud API output implementation for alert dispatch."""
import logging
import requests
from src.outputs.base import BaseOutput

logger = logging.getLogger(__name__)
GRAPH_API_URL = "https://graph.facebook.com/v21.0"


class WhatsAppOutput(BaseOutput):
    def __init__(self, phone_number_id: str, access_token: str, recipient: str,
                 template_name: str, language_code: str = "es_MX") -> None:
        self.phone_number_id = phone_number_id
        self.access_token = access_token
        self.recipient = recipient
        self.template_name = template_name
        self.language_code = language_code

    def send_alert(self, message: str, glucose_value: int, level: str) -> bool:
        url = f"{GRAPH_API_URL}/{self.phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"}
        payload = {
            "messaging_product": "whatsapp", "to": self.recipient, "type": "template",
            "template": {
                "name": self.template_name, "language": {"code": self.language_code},
                "components": [{"type": "body", "parameters": [{"type": "text", "text": message}]}],
            },
        }
        logger.debug("WhatsApp sending to %s via template '%s'", self.recipient, self.template_name)
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            if resp.ok:
                logger.info("WhatsApp message sent to %s", self.recipient)
                return True
            logger.error("WhatsApp API error %d: %s", resp.status_code, resp.text[:200])
            return False
        except requests.RequestException as e:
            logger.error("WhatsApp request failed: %s", e)
            return False
