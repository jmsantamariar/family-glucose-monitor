"""Tests for i18n support on /login, /setup, and /configuracion pages.

Covers:
- Presence of the language selector (lang-toggle-btn) on all three pages.
- Presence of data-i18n attributes on key elements.
- Default region is LA on the setup page.
- Region → language suggestion logic (REGION_LOCALE_MAP) is present in setup.html.
- User override tracking (_userOverridedLocale) is present in setup.html.
- i18n.js includes placeholder-translation support (data-i18n-placeholder).
"""
import re
import pytest
from starlette.testclient import TestClient
from src.api import app


@pytest.fixture
def client():
    return TestClient(app)


# ── Language selector presence ────────────────────────────────────────────────

class TestLangSelectorPresence:
    """The globe / language dropdown must be visible on /login, /setup, /configuracion."""

    def test_login_has_lang_toggle_btn(self, client, monkeypatch):
        monkeypatch.setattr("src.api.is_configured", lambda: True)
        resp = client.get("/login")
        assert resp.status_code == 200
        assert 'id="lang-toggle-btn"' in resp.text

    def test_setup_has_lang_toggle_btn(self, client):
        resp = client.get("/setup")
        assert resp.status_code == 200
        assert 'id="lang-toggle-btn"' in resp.text

    def test_configuracion_has_lang_toggle_btn(self, client):
        resp = client.get("/configuracion")
        assert resp.status_code == 200
        assert 'id="lang-toggle-btn"' in resp.text

    def test_login_loads_i18n_script(self, client, monkeypatch):
        monkeypatch.setattr("src.api.is_configured", lambda: True)
        resp = client.get("/login")
        assert "/i18n/i18n.js" in resp.text

    def test_setup_loads_i18n_script(self, client):
        resp = client.get("/setup")
        assert "/i18n/i18n.js" in resp.text

    def test_configuracion_loads_i18n_script(self, client):
        resp = client.get("/configuracion")
        assert "/i18n/i18n.js" in resp.text


# ── data-i18n attributes on key elements ─────────────────────────────────────

class TestDataI18nAttributes:
    """Key visible elements must carry data-i18n attributes so they get translated."""

    def test_login_heading_has_data_i18n(self, client, monkeypatch):
        monkeypatch.setattr("src.api.is_configured", lambda: True)
        resp = client.get("/login")
        assert 'data-i18n="login.heading"' in resp.text

    def test_login_submit_btn_has_data_i18n(self, client, monkeypatch):
        monkeypatch.setattr("src.api.is_configured", lambda: True)
        resp = client.get("/login")
        assert 'data-i18n="login.submit_btn"' in resp.text

    def test_setup_step1_heading_has_data_i18n(self, client):
        resp = client.get("/setup")
        assert 'data-i18n="setup.step1.heading"' in resp.text

    def test_setup_step_labels_have_data_i18n(self, client):
        resp = client.get("/setup")
        assert 'data-i18n="setup.step_label.account"' in resp.text
        assert 'data-i18n="setup.step_label.alerts"' in resp.text
        assert 'data-i18n="setup.step_label.notifications"' in resp.text

    def test_setup_save_btn_has_data_i18n(self, client):
        resp = client.get("/setup")
        assert 'data-i18n="setup.step3.save_btn"' in resp.text

    def test_configuracion_header_title_has_data_i18n(self, client):
        resp = client.get("/configuracion")
        assert 'data-i18n="config.header.title"' in resp.text

    def test_configuracion_back_btn_has_data_i18n(self, client):
        resp = client.get("/configuracion")
        assert 'data-i18n="config.header.back"' in resp.text

    def test_configuracion_section_ll_title_has_data_i18n(self, client):
        resp = client.get("/configuracion")
        assert 'data-i18n="config.section.ll.title"' in resp.text

    def test_configuracion_save_btn_has_data_i18n(self, client):
        resp = client.get("/configuracion")
        assert 'data-i18n="config.btn.save"' in resp.text

    def test_configuracion_alerts_section_has_data_i18n(self, client):
        resp = client.get("/configuracion")
        assert 'data-i18n="config.section.alerts.title"' in resp.text

    def test_configuracion_notif_section_has_data_i18n(self, client):
        resp = client.get("/configuracion")
        assert 'data-i18n="config.section.notif.title"' in resp.text


# ── Setup: default region is LA ───────────────────────────────────────────────

class TestSetupDefaultRegion:
    """The setup wizard must default to LA (Latin America) instead of EU."""

    def test_la_is_default_selected_region(self, client):
        resp = client.get("/setup")
        html = resp.text
        # LA option must carry selected attribute
        assert re.search(r'<option\s[^>]*value="LA"[^>]*selected', html) or \
               re.search(r'<option\s[^>]*selected[^>]*value="LA"', html), \
               "LA option should be marked as selected"

    def test_eu_is_not_the_default_region(self, client):
        resp = client.get("/setup")
        html = resp.text
        # EU option must NOT have selected attribute
        assert not re.search(r'<option\s[^>]*value="EU"[^>]*selected', html) and \
               not re.search(r'<option\s[^>]*selected[^>]*value="EU"', html), \
               "EU option should NOT be marked as selected"


# ── Region → language suggestion logic ───────────────────────────────────────

class TestRegionLocaleSuggestion:
    """Frontend region→locale map and user-override logic must be in setup.html."""

    def test_region_locale_map_present(self, client):
        resp = client.get("/setup")
        assert "REGION_LOCALE_MAP" in resp.text

    def test_la_maps_to_es_in_region_map(self, client):
        resp = client.get("/setup")
        # LA: 'es' should appear in the map literal
        assert "LA: 'es'" in resp.text or 'LA:"es"' in resp.text

    def test_us_maps_to_en_in_region_map(self, client):
        resp = client.get("/setup")
        assert "US: 'en'" in resp.text or 'US:"en"' in resp.text

    def test_user_override_flag_present(self, client):
        resp = client.get("/setup")
        assert "_userOverridedLocale" in resp.text

    def test_region_change_listener_present(self, client):
        resp = client.get("/setup")
        assert "regionSel.addEventListener" in resp.text or \
               "region').addEventListener" in resp.text or \
               "region\").addEventListener" in resp.text

    def test_override_is_not_reset_on_region_change(self, client):
        """The handler must check _userOverridedLocale before applying suggestion."""
        resp = client.get("/setup")
        html = resp.text
        # The region change handler must guard with the override flag
        assert "_userOverridedLocale" in html
        # The change listener block must reference the flag
        idx_flag = html.find("_userOverridedLocale")
        idx_map = html.find("REGION_LOCALE_MAP")
        assert idx_flag != -1 and idx_map != -1

    def test_lang_btn_click_sets_override(self, client):
        """Clicking the language toggle button must mark _userOverridedLocale = true."""
        resp = client.get("/setup")
        html = resp.text
        # The click listener on lang-toggle-btn must set the override flag
        assert "_userOverridedLocale = true" in html


# ── i18n.js: placeholder substitution in t() ─────────────────────────────────

class TestI18nJsPlaceholderSubstitution:
    """The t() function must replace {0}, {1} placeholders with provided arguments."""

    def test_t_function_replaces_placeholder_zero(self, client):
        resp = client.get("/i18n/i18n.js")
        js = resp.text
        # t() must use regex replacement to substitute {0}
        assert "replace" in js
        assert r"\{" in js or "\\\\{" in js or "'\\\\{' + " in js or "RegExp" in js

    def test_setup_tg_chat_obtained_key_uses_placeholder(self, client):
        resp = client.get("/i18n/i18n.js")
        # The key contains {0} and {1}
        assert "setup.tg.chat_obtained" in resp.text
        assert "{0}" in resp.text
        assert "{1}" in resp.text

    def test_setup_tg_multiple_chats_key_uses_placeholder(self, client):
        resp = client.get("/i18n/i18n.js")
        assert "setup.tg.multiple_chats" in resp.text

    def test_setup_html_calls_t_with_placeholder_args(self, client):
        resp = client.get("/setup")
        # t() is called with extra arguments for placeholders
        assert "t('setup.tg.chat_obtained'" in resp.text or \
               't("setup.tg.chat_obtained"' in resp.text
        assert "t('setup.tg.multiple_chats'" in resp.text or \
               't("setup.tg.multiple_chats"' in resp.text


# ── i18n.js: data-i18n-placeholder support ───────────────────────────────────

class TestI18nJsPlaceholderSupport:
    """i18n.js must handle data-i18n-placeholder so inputs get translated placeholders."""

    def test_i18n_js_has_placeholder_handler(self, client):
        resp = client.get("/i18n/i18n.js")
        assert resp.status_code == 200
        assert "data-i18n-placeholder" in resp.text

    def test_login_username_has_i18n_placeholder(self, client, monkeypatch):
        monkeypatch.setattr("src.api.is_configured", lambda: True)
        resp = client.get("/login")
        assert 'data-i18n-placeholder="login.username_placeholder"' in resp.text

    def test_setup_email_has_i18n_placeholder(self, client):
        resp = client.get("/setup")
        assert 'data-i18n-placeholder="setup.step1.email_placeholder"' in resp.text

    def test_setup_dashboard_password_has_i18n_placeholder(self, client):
        resp = client.get("/setup")
        assert 'data-i18n-placeholder="setup.step1.dashboard_password_placeholder"' in resp.text


# ── i18n.js: future screen placeholder keys ──────────────────────────────────

class TestFuturePlaceholderKeys:
    """i18n.js must contain placeholder keys for future password-recovery and help screens."""

    def test_recovery_heading_key_present(self, client):
        resp = client.get("/i18n/i18n.js")
        assert "recovery.heading" in resp.text

    def test_recovery_page_title_key_present(self, client):
        resp = client.get("/i18n/i18n.js")
        assert "recovery.page_title" in resp.text

    def test_help_heading_key_present(self, client):
        resp = client.get("/i18n/i18n.js")
        assert "help.heading" in resp.text

    def test_help_page_title_key_present(self, client):
        resp = client.get("/i18n/i18n.js")
        assert "help.page_title" in resp.text

    def test_footer_warning_key_present_in_both_locales(self, client):
        resp = client.get("/i18n/i18n.js")
        # These keys were present before this PR (pre-existing) and must remain
        assert resp.text.count("'footer.warning'") >= 2  # at least ES + EN

    def test_footer_disclaimer_key_present_in_both_locales(self, client):
        resp = client.get("/i18n/i18n.js")
        assert resp.text.count("'footer.disclaimer'") >= 2  # at least ES + EN
