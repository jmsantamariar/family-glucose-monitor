#!/usr/bin/env python3
"""Validate Telegram bot connection by sending a test message."""
import os
import sys
from pathlib import Path

import requests
import yaml

TELEGRAM_API = "https://api.telegram.org"


def main():
    config_path = os.environ.get("CONFIG_PATH", str(Path(__file__).resolve().parent / "config.yaml"))
    if not os.path.exists(config_path):
        print(f"Config not found: {config_path}")
        sys.exit(1)
    with open(config_path) as f:
        config = yaml.safe_load(f)
    telegram_cfg = None
    for out in config.get("outputs", []):
        if out.get("type") == "telegram":
            telegram_cfg = out
            break
    if not telegram_cfg:
        print("No telegram output configured")
        sys.exit(1)
    bot_token = telegram_cfg.get("bot_token", "")
    chat_id = telegram_cfg.get("chat_id", "")
    if not bot_token or not chat_id:
        print("Missing bot_token or chat_id in telegram config")
        sys.exit(1)
    print(f"Sending test message to chat {chat_id}...")
    url = f"{TELEGRAM_API}/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": "🧪 Test: Family Glucose Monitor is connected!", "parse_mode": "HTML"}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.ok:
            print("Message sent successfully!")
        else:
            print(f"Telegram error {resp.status_code}: {resp.text[:200]}")
            sys.exit(1)
    except requests.RequestException as e:
        print(f"Request failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
