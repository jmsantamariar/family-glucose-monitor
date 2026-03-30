"""Validate Telegram Bot configuration by sending a test message."""
import sys


def main() -> None:
    try:
        import yaml
    except ImportError:
        print("ERROR: PyYAML not installed. Run: pip install PyYAML")
        sys.exit(1)

    try:
        import requests
    except ImportError:
        print("ERROR: requests not installed. Run: pip install requests")
        sys.exit(1)

    try:
        with open("config.yaml") as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        print("ERROR: config.yaml not found. Copy config.example.yaml to config.yaml")
        sys.exit(1)

    outputs = config.get("outputs", [])
    telegram_cfg = next(
        (o for o in outputs if o.get("type") == "telegram"), None
    )
    if telegram_cfg is None:
        print("ERROR: No telegram output found in config.yaml [outputs] section")
        sys.exit(1)

    bot_token = telegram_cfg.get("bot_token", "")
    chat_id = telegram_cfg.get("chat_id", "")

    if not bot_token:
        print("ERROR: bot_token is empty in telegram output config")
        sys.exit(1)
    if not chat_id:
        print("ERROR: chat_id is empty in telegram output config")
        sys.exit(1)

    test_message = "✅ <b>Family Glucose Monitor</b> — Telegram configurado correctamente."
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": test_message, "parse_mode": "HTML"}

    print(f"Sending test message to chat {chat_id}...")
    try:
        resp = requests.post(url, json=payload, timeout=10)
    except requests.RequestException as e:
        print(f"ERROR: Request failed: {e}")
        sys.exit(1)

    if resp.ok:
        print("✓ Test message sent successfully!")
    else:
        print(f"ERROR: Telegram API returned {resp.status_code}: {resp.text[:300]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
