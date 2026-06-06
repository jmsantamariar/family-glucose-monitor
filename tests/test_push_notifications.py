"""Tests for Web Push notification endpoints in src/api.py."""
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import src.api as api_module
import src.push_subscriptions as push_subs_module
from src.api import app


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    monkeypatch.setattr(api_module, "_ALLOW_AUTH_DISABLED", True)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def init_push_db(tmp_path, monkeypatch):
    """Initialise an in-memory (temporary) push subscriptions DB for each test."""
    db_path = str(tmp_path / "push_subscriptions.db")
    push_subs_module.init_db(db_path)
    yield
    # Reset module-level DB path so the next test gets a fresh DB.
    push_subs_module._db_path = None


# ── GET /api/push/vapid-public-key ───────────────────────────────────────────

class TestVapidPublicKeyEndpoint:
    def test_returns_200(self, client):
        with patch("src.api.get_vapid_public_key", return_value="fake-pub-key"):
            resp = client.get("/api/push/vapid-public-key")
        assert resp.status_code == 200

    def test_returns_public_key(self, client):
        with patch("src.api.get_vapid_public_key", return_value="BGtest_public_key"):
            resp = client.get("/api/push/vapid-public-key")
        assert resp.json()["publicKey"] == "BGtest_public_key"

    def test_returns_500_on_error(self, client):
        with patch("src.api.get_vapid_public_key", side_effect=RuntimeError("no keys")):
            resp = client.get("/api/push/vapid-public-key")
        assert resp.status_code == 500

    def test_endpoint_is_auth_exempt(self):
        """The VAPID public-key endpoint must be listed in _AUTH_EXEMPT_PATHS."""
        assert "/api/push/vapid-public-key" in api_module._AUTH_EXEMPT_PATHS


# ── POST /api/push/subscribe ─────────────────────────────────────────────────

class TestPushSubscribeEndpoint:
    _VALID_PAYLOAD = {
        "endpoint": "https://fcm.googleapis.com/fcm/send/fake-endpoint",
        "keys": {
            "p256dh": "BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QTpQtUbVlUls0VJXg7A8u-Ts1XbjhazAkj7I99e8QcYP7DkM",
            "auth": "tBHItJI5svbpez7KI4CCXg",
        },
    }

    def test_returns_200_on_valid_subscription(self, client):
        resp = client.post(
            "/api/push/subscribe",
            json=self._VALID_PAYLOAD,
        )
        assert resp.status_code == 200

    def test_subscription_is_persisted(self, client):
        client.post("/api/push/subscribe", json=self._VALID_PAYLOAD)
        subs = push_subs_module.get_all_subscriptions()
        assert len(subs) == 1
        assert subs[0]["endpoint"] == self._VALID_PAYLOAD["endpoint"]

    def test_missing_endpoint_returns_422(self, client):
        resp = client.post(
            "/api/push/subscribe",
            json={"keys": {"p256dh": "aaa", "auth": "bbb"}},
        )
        assert resp.status_code == 422

    def test_missing_keys_returns_422(self, client):
        resp = client.post(
            "/api/push/subscribe",
            json={"endpoint": "https://example.com/push"},
        )
        assert resp.status_code == 422

    def test_missing_p256dh_returns_422(self, client):
        resp = client.post(
            "/api/push/subscribe",
            json={"endpoint": "https://example.com/push", "keys": {"auth": "bbb"}},
        )
        assert resp.status_code == 422

    def test_invalid_json_returns_400(self, client):
        resp = client.post(
            "/api/push/subscribe",
            content=b"not-json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400

    def test_duplicate_endpoint_upserts_silently(self, client):
        client.post("/api/push/subscribe", json=self._VALID_PAYLOAD)
        client.post("/api/push/subscribe", json=self._VALID_PAYLOAD)
        subs = push_subs_module.get_all_subscriptions()
        assert len(subs) == 1

    def test_db_error_returns_500(self, client, monkeypatch):
        monkeypatch.setattr(
            push_subs_module, "save_subscription", MagicMock(side_effect=RuntimeError("db error"))
        )
        resp = client.post("/api/push/subscribe", json=self._VALID_PAYLOAD)
        assert resp.status_code == 500

    def _payload_with_endpoint(self, endpoint):
        return {**self._VALID_PAYLOAD, "endpoint": endpoint}

    def test_http_endpoint_returns_422(self, client):
        resp = client.post(
            "/api/push/subscribe",
            json=self._payload_with_endpoint("http://fcm.googleapis.com/fcm/send/abc"),
        )
        assert resp.status_code == 422

    def test_unknown_host_returns_422(self, client):
        resp = client.post(
            "/api/push/subscribe",
            json=self._payload_with_endpoint("https://attacker.example.com/push"),
        )
        assert resp.status_code == 422

    def test_host_suffix_spoof_returns_422(self, client):
        """A host merely *containing* an allowed name must be rejected."""
        resp = client.post(
            "/api/push/subscribe",
            json=self._payload_with_endpoint("https://fcm.googleapis.com.evil.example/send/abc"),
        )
        assert resp.status_code == 422

    def test_malformed_url_returns_422(self, client):
        resp = client.post(
            "/api/push/subscribe",
            json=self._payload_with_endpoint("not a url"),
        )
        assert resp.status_code == 422

    @pytest.mark.parametrize(
        "endpoint",
        [
            "https://fcm.googleapis.com/fcm/send/abc",
            "https://updates.push.services.mozilla.com/wpush/v2/abc",
            "https://web.push.apple.com/QAbc",
            "https://es1.notify.windows.com/w/?token=abc",
            "https://webpush.push.apple.com/QAbc",
        ],
    )
    def test_known_push_services_return_200(self, client, endpoint):
        resp = client.post(
            "/api/push/subscribe",
            json=self._payload_with_endpoint(endpoint),
        )
        assert resp.status_code == 200


# ── POST /api/push/unsubscribe ───────────────────────────────────────────────

class TestPushUnsubscribeEndpoint:
    _ENDPOINT = "https://fcm.googleapis.com/fcm/send/fake-endpoint-to-remove"

    def _subscribe(self, client):
        client.post(
            "/api/push/subscribe",
            json={
                "endpoint": self._ENDPOINT,
                "keys": {"p256dh": "BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QTpQtUbVlUls0VJXg7A8u-Ts1XbjhazAkj7I99e8QcYP7DkM", "auth": "tBHItJI5svbpez7KI4CCXg"},
            },
        )

    def test_returns_200(self, client):
        self._subscribe(client)
        resp = client.post("/api/push/unsubscribe", json={"endpoint": self._ENDPOINT})
        assert resp.status_code == 200

    def test_subscription_is_removed(self, client):
        self._subscribe(client)
        assert len(push_subs_module.get_all_subscriptions()) == 1
        client.post("/api/push/unsubscribe", json={"endpoint": self._ENDPOINT})
        assert len(push_subs_module.get_all_subscriptions()) == 0

    def test_missing_endpoint_returns_422(self, client):
        resp = client.post("/api/push/unsubscribe", json={})
        assert resp.status_code == 422

    def test_nonexistent_endpoint_returns_200(self, client):
        resp = client.post(
            "/api/push/unsubscribe",
            json={"endpoint": "https://example.com/nonexistent"},
        )
        assert resp.status_code == 200

    def test_invalid_json_returns_400(self, client):
        resp = client.post(
            "/api/push/unsubscribe",
            content=b"not-json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400

    def test_db_error_returns_500(self, client, monkeypatch):
        monkeypatch.setattr(
            push_subs_module, "delete_subscription", MagicMock(side_effect=RuntimeError("db error"))
        )
        resp = client.post(
            "/api/push/unsubscribe", json={"endpoint": "https://example.com/push"}
        )
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# send_alert — legacy/tampered endpoints outside the allowlist are never
# POSTed to and get pruned (Copilot review on PR #97: the subscribe-time
# allowlist alone does not cover rows persisted before the hardening).
# ---------------------------------------------------------------------------

class TestSendAlertEndpointFiltering:
    _GOOD = "https://fcm.googleapis.com/fcm/send/good"
    _BAD = "https://attacker.example.com/exfil"

    def _output(self):
        from src.outputs.webpush import WebPushOutput

        return WebPushOutput(vapid_subject="mailto:test@example.com", icon_url="")

    def test_disallowed_endpoint_is_not_posted_and_pruned(self):
        push_subs_module.save_subscription(self._BAD, "p", "a")
        push_subs_module.save_subscription(self._GOOD, "p", "a")
        with (
            patch("src.outputs.webpush.webpush") as mock_webpush,
            patch("src.outputs.webpush._load_or_generate_vapid", return_value=("key", "pub")),
        ):
            self._output().send_alert("msg", 100, "low")
        posted = [c.kwargs["subscription_info"]["endpoint"] for c in mock_webpush.call_args_list]
        assert self._BAD not in posted
        assert self._GOOD in posted
        remaining = [s["endpoint"] for s in push_subs_module.get_all_subscriptions()]
        assert self._BAD not in remaining
        assert self._GOOD in remaining


# ---------------------------------------------------------------------------
# Notification titles for trend-only levels
# ---------------------------------------------------------------------------

def test_title_for_trend_levels():
    from src.outputs.webpush import _title_for_level

    assert _title_for_level("trend_falling_fast") == "📉 Glucosa bajando rápido"
    assert _title_for_level("trend_rising_fast") == "📈 Glucosa subiendo rápido"
    # A trend-only alert must never render as "normal".
    for lvl in ("trend_falling", "trend_rising", "trend_falling_fast", "trend_rising_fast"):
        assert "normal" not in _title_for_level(lvl).lower()
    assert _title_for_level("unknown_level") == "🔔 Alerta de glucosa"
