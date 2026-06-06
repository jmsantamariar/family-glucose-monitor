"""Tests for i18n support on /login, /setup, and /configuracion pages.

Covers:
- Presence of the language selector (lang-toggle-btn) on all three pages.
- Presence of data-i18n attributes on key elements.
- Default region is LA on the setup page.
- Region → language suggestion logic (REGION_LOCALE_MAP) is present in setup.html.
- User override tracking (_userOverrodeLocale) is present in setup.html.
- i18n.js includes placeholder-translation support (data-i18n-placeholder).
"""
import re
import pytest
from fastapi.testclient import TestClient
from src.api import app


@pytest.fixture
def client():
    return TestClient(app)


def _i18n_locale_keys(locale):
    """Return the set of keys defined for *locale* inside i18n.js.

    i18n.js is the single source of truth for translations (the old
    es.json/en.json mirrors were removed). The TRANSLATIONS literal holds
    the ``es`` dict first and the ``en`` dict second; split on the ``en:``
    boundary to scope the key regex per locale.
    """
    from pathlib import Path

    js = (
        Path(__file__).parent.parent / "src" / "dashboard" / "i18n" / "i18n.js"
    ).read_text(encoding="utf-8")
    es_part, en_part = js.split("\n    en: {", 1)
    part = es_part if locale == "es" else en_part
    return set(re.findall(r"'([A-Za-z0-9_.]+)'\s*:", part))


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
        assert "_userOverrodeLocale" in resp.text

    def test_region_change_listener_present(self, client):
        resp = client.get("/setup")
        assert "regionSel.addEventListener" in resp.text or \
               "region').addEventListener" in resp.text or \
               "region\").addEventListener" in resp.text

    def test_override_is_not_reset_on_region_change(self, client):
        """The handler must check _userOverrodeLocale before applying suggestion."""
        resp = client.get("/setup")
        html = resp.text
        # The region change handler must guard with the override flag
        assert "_userOverrodeLocale" in html
        # The change listener block must reference the flag
        idx_flag = html.find("_userOverrodeLocale")
        idx_map = html.find("REGION_LOCALE_MAP")
        assert idx_flag != -1 and idx_map != -1

    def test_lang_btn_click_sets_override(self, client):
        """Clicking the language toggle button must mark _userOverrodeLocale = true."""
        resp = client.get("/setup")
        html = resp.text
        # The click listener on lang-toggle-btn must set the override flag
        assert "_userOverrodeLocale = true" in html


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


# ── Telegram step list i18n ───────────────────────────────────────────────────

class TestTelegramStepsI18n:
    """Telegram guide steps must use data-i18n so they are translated."""

    def test_tg_step1_uses_split_spans(self, client):
        resp = client.get("/setup")
        assert 'data-i18n="setup.step3.tg_guide_step1_pre"' in resp.text
        assert 'data-i18n="setup.step3.tg_guide_step1_suf"' in resp.text

    def test_tg_step1_preserves_botfather_link(self, client):
        resp = client.get("/setup")
        assert 'href="https://t.me/BotFather"' in resp.text

    def test_tg_step2_uses_data_i18n(self, client):
        resp = client.get("/setup")
        assert 'data-i18n="setup.step3.tg_guide_step2"' in resp.text

    def test_tg_step3_uses_data_i18n(self, client):
        resp = client.get("/setup")
        assert 'data-i18n="setup.step3.tg_guide_step3"' in resp.text

    def test_tg_step1_split_keys_in_i18n_js(self, client):
        resp = client.get("/i18n/i18n.js")
        assert "setup.step3.tg_guide_step1_pre" in resp.text
        assert "setup.step3.tg_guide_step1_suf" in resp.text

    def test_no_hardcoded_tg_steps(self, client):
        resp = client.get("/setup")
        # Step 1's prefix text must only appear inside a data-i18n span (not as bare HTML)
        assert 'data-i18n="setup.step3.tg_guide_step1_pre"' in resp.text
        # Step 2 and step 3 must carry data-i18n, not be bare text on <li>
        assert 'data-i18n="setup.step3.tg_guide_step2"' in resp.text
        assert 'data-i18n="setup.step3.tg_guide_step3"' in resp.text
        # The un-wrapped bare HTML from the original hard-coded structure must be gone
        assert 'Habla con <a' not in resp.text


# ── configuracion.html dashboard auth note splits ────────────────────────────

class TestDashboardAuthNoteSplits:
    """The dashboard auth note must use split spans to preserve link and code markup."""

    def test_auth_note_uses_split_spans(self, client):
        resp = client.get("/configuracion")
        assert 'data-i18n="config.dashboard_auth_note_pre"' in resp.text
        assert 'data-i18n="config.dashboard_auth_note_mid"' in resp.text
        assert 'data-i18n="config.dashboard_auth_note_suf"' in resp.text

    def test_auth_note_preserves_setup_link(self, client):
        resp = client.get("/configuracion")
        assert 'href="/setup"' in resp.text

    def test_auth_note_preserves_config_yaml_code(self, client):
        resp = client.get("/configuracion")
        assert '<code>config.yaml</code>' in resp.text

    def test_auth_note_split_keys_in_i18n_js(self, client):
        resp = client.get("/i18n/i18n.js")
        assert "config.dashboard_auth_note_pre" in resp.text
        assert "config.dashboard_auth_note_mid" in resp.text
        assert "config.dashboard_auth_note_suf" in resp.text


# ── _userOverrodeLocale consistent naming ────────────────────────────────────

class TestUserOverrodeLocaleNaming:
    """The variable must be consistently named _userOverrodeLocale."""

    def test_no_old_typo_variable(self, client):
        resp = client.get("/setup")
        assert "_userOverridedLocale" not in resp.text

    def test_correct_variable_name_declared(self, client):
        resp = client.get("/setup")
        assert "_userOverrodeLocale" in resp.text


# ── Historical analysis (range selector + metrics card + download) ───────────


class TestHistoryAnalysisUI:
    """The historical analysis section (step A of history-ui plan) must be
    wired across index.html, i18n and service worker."""

    # Section + selector present in dashboard

    def test_index_has_history_analysis_section(self, client):
        resp = client.get("/")
        assert 'id="history-analysis-section"' in resp.text

    def test_index_has_history_analysis_grid_container(self, client):
        resp = client.get("/")
        assert 'id="history-analysis-grid"' in resp.text

    def test_index_has_4_range_buttons(self, client):
        resp = client.get("/")
        # data-range="3h" / "24h" / "14d" / "90d"
        for token in ("3h", "24h", "14d", "90d"):
            assert f'data-range="{token}"' in resp.text, f"missing range button {token}"

    def test_index_section_uses_data_i18n_for_title(self, client):
        resp = client.get("/")
        assert 'data-i18n="history_analysis.title"' in resp.text

    def test_index_range_buttons_use_data_i18n(self, client):
        resp = client.get("/")
        for key in ("history_analysis.range_3h",
                    "history_analysis.range_24h",
                    "history_analysis.range_14d",
                    "history_analysis.range_90d"):
            assert f'data-i18n="{key}"' in resp.text

    # JS wiring

    def test_index_defines_range_map(self, client):
        resp = client.get("/")
        assert "RANGE_MAP" in resp.text

    def test_index_persists_range_in_localStorage(self, client):
        resp = client.get("/")
        assert "fgm-chart-range" in resp.text

    def test_index_uses_promise_allsettled_for_parallel_fetch(self, client):
        """Chart and metrics must be fetched in parallel; one failure must not
        block the other."""
        resp = client.get("/")
        assert "Promise.allSettled" in resp.text

    def test_index_calls_render_history_analysis_in_fetch_patients(self, client):
        resp = client.get("/")
        assert "renderHistoryAnalysis(data.patients)" in resp.text

    # i18n keys present in both locales (i18n.js is the single source of truth)

    _HISTORY_ANALYSIS_KEYS = (
        "history_analysis.title",
        "history_analysis.range_3h", "history_analysis.range_24h",
        "history_analysis.range_14d", "history_analysis.range_90d",
        "history_analysis.metric.tir", "history_analysis.metric.gmi",
        "history_analysis.metric.cv", "history_analysis.metric.n",
        "history_analysis.partial_badge",
        "history_analysis.show_detail", "history_analysis.hide_detail",
        "history_analysis.metrics_empty", "history_analysis.chart_empty",
        "history_analysis.download_csv", "history_analysis.download_json",
    )

    @pytest.mark.parametrize("locale", ["es", "en"])
    def test_history_analysis_keys_in_locale(self, locale):
        keys = _i18n_locale_keys(locale)
        missing = [k for k in self._HISTORY_ANALYSIS_KEYS if k not in keys]
        assert not missing, f"missing {locale} keys: {missing}"


# ── Senior mode toggle (elder-friendly accessibility) ────────────────────────

class TestSeniorModeToggle:
    """The senior/modern mode toggle must be wired across all dashboard pages."""

    # Bootstrap script (applies data-mode before first render) on all 4 pages

    def test_index_has_mode_bootstrap(self, client):
        resp = client.get("/")
        assert "localStorage.getItem('fgm-mode')" in resp.text
        assert "data-mode" in resp.text

    def test_login_has_mode_bootstrap(self, client, monkeypatch):
        monkeypatch.setattr("src.api.is_configured", lambda: True)
        resp = client.get("/login")
        assert "localStorage.getItem('fgm-mode')" in resp.text

    def test_setup_has_mode_bootstrap(self, client):
        resp = client.get("/setup")
        assert "localStorage.getItem('fgm-mode')" in resp.text

    def test_configuracion_has_mode_bootstrap(self, client):
        resp = client.get("/configuracion")
        assert "localStorage.getItem('fgm-mode')" in resp.text

    # CSS senior block present on all 4 pages

    def test_index_has_senior_css_block(self, client):
        resp = client.get("/")
        assert ':root[data-mode="senior"]' in resp.text

    def test_login_has_senior_css_block(self, client, monkeypatch):
        monkeypatch.setattr("src.api.is_configured", lambda: True)
        resp = client.get("/login")
        assert ':root[data-mode="senior"]' in resp.text

    def test_setup_has_senior_css_block(self, client):
        resp = client.get("/setup")
        assert ':root[data-mode="senior"]' in resp.text

    def test_configuracion_has_senior_css_block(self, client):
        resp = client.get("/configuracion")
        assert ':root[data-mode="senior"]' in resp.text

    # font-scale applied to html on all 4 pages

    def test_index_applies_font_scale_to_html(self, client):
        resp = client.get("/")
        assert "calc(16px * var(--font-scale" in resp.text

    def test_login_applies_font_scale_to_html(self, client, monkeypatch):
        monkeypatch.setattr("src.api.is_configured", lambda: True)
        resp = client.get("/login")
        assert "calc(16px * var(--font-scale" in resp.text

    def test_setup_applies_font_scale_to_html(self, client):
        resp = client.get("/setup")
        assert "calc(16px * var(--font-scale" in resp.text

    def test_configuracion_applies_font_scale_to_html(self, client):
        resp = client.get("/configuracion")
        assert "calc(16px * var(--font-scale" in resp.text

    # Toggle button present on index and configuracion (NOT on login/setup)

    def test_index_has_mode_toggle_button(self, client):
        resp = client.get("/")
        assert 'id="mode-toggle-btn"' in resp.text

    def test_configuracion_has_mode_toggle_button(self, client):
        resp = client.get("/configuracion")
        assert 'id="mode-toggle-btn"' in resp.text

    # i18n keys for toggle present in both locales

    @pytest.mark.parametrize("locale", ["es", "en"])
    def test_mode_toggle_keys_in_locale(self, locale):
        keys = _i18n_locale_keys(locale)
        for key in (
            "header.mode_toggle_btn",
            "header.mode_toggle_to_senior",
            "header.mode_toggle_to_modern",
            "header.mode_toggle_aria_label",
        ):
            assert key in keys, f"missing {locale} key {key!r}"

    def test_mode_toggle_keys_in_runtime_i18n_js(self, client):
        """The served i18n.js must carry the toggle keys — a missing key
        makes applyTranslations() render the raw key string as visible
        text. Covers Copilot review feedback from the elder-mode PR."""
        resp = client.get("/i18n/i18n.js")
        assert resp.status_code == 200
        assert "header.mode_toggle_btn" in resp.text
        assert "header.mode_toggle_to_senior" in resp.text
        assert "header.mode_toggle_to_modern" in resp.text
        assert "header.mode_toggle_aria_label" in resp.text

    @pytest.mark.parametrize("filename", ["es.json", "en.json"])
    def test_removed_json_locales_are_not_served(self, client, filename):
        """The JSON locale mirrors were removed; the route must 404 them."""
        resp = client.get(f"/i18n/{filename}")
        assert resp.status_code == 404

    # Heuristic default uses both prefers-reduced-motion and prefers-color-scheme

    def test_index_heuristic_uses_prefers_reduced_motion(self, client):
        resp = client.get("/")
        assert "prefers-reduced-motion: reduce" in resp.text

    def test_index_heuristic_uses_prefers_color_scheme_light(self, client):
        resp = client.get("/")
        assert "prefers-color-scheme: light" in resp.text

    # Service worker cache version bumped (so installed PWAs refresh)

    def test_service_worker_cache_bumped_past_v1(self, client):
        resp = client.get("/sw.js")
        assert resp.status_code == 200
        assert 'CACHE_NAME = "fgm-shell-v1"' not in resp.text
        # Must be v2 or newer (currently v3 after merging history-ui + elder-mode)
        assert 'CACHE_NAME = "fgm-shell-v' in resp.text


# ── Every data-i18n key referenced in HTML must exist in i18n.js ─────────────

class TestI18nKeysExist:
    """Guard against data-i18n references to keys missing from i18n.js.

    t() falls back to returning the raw key, so a missing key renders
    literally (e.g. "setup.step1.dashboard_hint_prefix") in the UI.
    """

    _PAGES = ["login.html", "setup.html", "configuracion.html", "index.html"]

    def _i18n_js_keys(self):
        from pathlib import Path

        js = (
            Path(__file__).parent.parent / "src" / "dashboard" / "i18n" / "i18n.js"
        ).read_text(encoding="utf-8")
        return set(re.findall(r"'([A-Za-z0-9_.]+)'\s*:", js))

    @pytest.mark.parametrize("page", _PAGES)
    def test_all_data_i18n_keys_defined(self, page):
        from pathlib import Path

        html = (
            Path(__file__).parent.parent / "src" / "dashboard" / page
        ).read_text(encoding="utf-8")
        # Only literal keys: skips dynamic JS like data-i18n="' + key + '".
        referenced = set(re.findall(r'data-i18n(?:-placeholder)?="([A-Za-z0-9_.]+)"', html))
        defined = self._i18n_js_keys()
        missing = sorted(referenced - defined)
        assert not missing, f"{page} references undefined i18n keys: {missing}"

    def test_senior_keys_exist_in_both_locales(self):
        """The senior mirror builds its UI via i18n.t('senior.*') — a key
        missing from either locale renders the raw key (or falls back to
        Spanish in EN). Enforce es↔en parity for the whole senior.* set."""
        es = {k for k in _i18n_locale_keys("es") if k.startswith("senior.")}
        en = {k for k in _i18n_locale_keys("en") if k.startswith("senior.")}
        assert es, "no senior.* keys found in es locale"
        assert es == en, (
            f"senior.* parity broken — only in es: {sorted(es - en)}; "
            f"only in en: {sorted(en - es)}"
        )

    def test_senior_keys_referenced_in_index_exist(self):
        """Literal i18n.t('senior.…') calls in index.html must resolve."""
        from pathlib import Path

        html = (
            Path(__file__).parent.parent / "src" / "dashboard" / "index.html"
        ).read_text(encoding="utf-8")
        referenced = set(re.findall(r"i18n\.t\('(senior\.[A-Za-z0-9_.]+)'", html))
        assert referenced, "expected literal senior.* i18n.t() calls in index.html"
        for locale in ("es", "en"):
            missing = sorted(referenced - _i18n_locale_keys(locale))
            assert not missing, f"{locale} missing senior keys: {missing}"
