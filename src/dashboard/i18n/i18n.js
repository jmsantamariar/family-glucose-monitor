/* ── Family Glucose Monitor — i18n helper ────────────────────────────────────
 * Lightweight vanilla-JS internationalisation helper.
 * - Reads active locale from localStorage key "fgm_locale" (default: "es").
 * - Applies translations to DOM elements carrying a data-i18n attribute.
 * - Exposes window.i18n = { t, setLocale, getLocale, applyTranslations }.
 * - Dispatches "fgm:localechange" on window when the locale is switched.
 * No external dependencies.  Both locales are embedded to avoid async loading.
 * The canonical source files are src/dashboard/i18n/es.json and en.json.
 * ──────────────────────────────────────────────────────────────────────────── */
(function () {
  'use strict';

  // ── Embedded translation tables ──────────────────────────────────────────
  var TRANSLATIONS = {
    es: {
      'header.last_update_prefix': 'Última actualización: ',
      'header.settings_btn': 'Configuración',
      'header.logout_btn': '⏏ Salir',
      'header.live_badge': '● LIVE',
      'alerts.title': '🔔 Historial de alertas (24h)',
      'alerts.total': 'Alertas totales',
      'alerts.high': 'Alertas ALTA',
      'alerts.low': 'Alertas BAJA',
      'alerts.trend': 'Alertas tendencia',
      'readings.section_title': '📊 Lecturas actuales',
      'table.patient': 'Paciente',
      'table.glucose': 'Glucosa',
      'table.trend': 'Tendencia',
      'table.level': 'Nivel',
      'table.trend_alert': 'Alerta tendencia',
      'table.last_reading': 'Última lectura',
      'push.title': '🔔 Notificaciones push:',
      'push.activate': 'Activar notificaciones',
      'push.deactivate': 'Desactivar notificaciones',
      'push.no_support': 'Tu navegador no soporta notificaciones push.',
      'push.blocked': '🔕 Notificaciones bloqueadas en el navegador.',
      'push.active': '✅ Notificaciones activas en este dispositivo.',
      'push.activated': '✅ ¡Notificaciones activadas!',
      'push.deactivated': '🔕 Notificaciones desactivadas.',
      'history.patient_label': 'Paciente:',
      'history.patient_all': 'Todos',
      'history.hours_label': 'Últimas:',
      'history.6h': '6 horas',
      'history.24h': '24 horas',
      'history.48h': '48 horas',
      'history.7d': '7 días',
      'chart.by_hour': 'Alertas por hora',
      'chart.by_level': 'Distribución por nivel',
      'chart.level_global': 'Distribución por nivel — Global',
      'chart.level_patient': 'Distribución por nivel — {0}',
      'chart.loading': '⏳ Cargando…',
      'chart.no_data': 'Sin datos suficientes',
      'history.section_title': 'Historial de alertas',
      'history.table.time': 'Hora',
      'history.table.patient': 'Paciente',
      'history.table.glucose': 'Glucosa',
      'history.table.level': 'Nivel',
      'history.table.message': 'Mensaje',
      'glucose_charts.title': '📉 Valores de glucosa en alertas',
      'footer.warning': '⚠️ Este no es un dispositivo médico.',
      'footer.disclaimer': 'Esta herramienta es solo para referencia informativa y no reemplaza la atención médica profesional ni los sistemas de alarma del medidor de glucosa.',
      'no_data.loading': '⏳ Cargando datos…',
      'no_data.waiting': '📭 Sin datos — esperando lecturas…',
      'no_data.history_loading': '⏳ Cargando historial…',
      'no_data.history_empty': '📭 Sin alertas en el período seleccionado.',
      'status.connected': 'Conectado',
      'status.reconnecting': 'Reconectando…',
      'status.disconnected': 'Sin conexión',
      'status.connecting': 'Conectando…',
      'time.now': 'ahora',
      'time.min_ago': 'hace {0} min',
      'time.hour_min_ago': 'hace {0}h {1}m',
      'level.low': 'BAJA',
      'level.high': 'ALTA',
      'level.normal': 'NORMAL',
      'trend.double_up': 'Subiendo muy rápido',
      'trend.single_up': 'Subiendo rápido',
      'trend.forty_five_up': 'Subiendo',
      'trend.flat': 'Estable',
      'trend.forty_five_down': 'Bajando',
      'trend.single_down': 'Bajando rápido',
      'trend.double_down': 'Bajando muy rápido',
      'trend_alert.falling_fast': '🔻 Bajando rápido',
      'trend_alert.falling': '📉 Bajando',
      'trend_alert.rising_fast': '🔺 Subiendo rápido',
      'trend_alert.rising': '📈 Subiendo',
      'card.mg_dl': 'mg/dL actual',
      'card.level': 'Nivel',
      'card.last_reading': 'Última lectura',
      'card.trend_prefix': 'Tendencia: ',
      'card.stable_trend': 'Tendencia estable',
      'stats.max': 'máx',
      'stats.avg': 'prom',
      'stats.min': 'mín',
      'chart_label.low': 'Baja',
      'chart_label.high': 'Alta',
      'chart_label.trend': 'Tendencia',
      'tir.high': 'Alta {0}%',
      'tir.range': '{0}% en rango',
      'tir.low': 'Baja {0}%',
      'zone.high': 'ALTA',
      'zone.low': 'BAJA',
      'zone.range': 'EN RANGO',
      'alert_level.low': 'BAJA',
      'alert_level.high': 'ALTA',
      'alert_level.trend': 'TENDENCIA',
      'lang.toggle': 'Cambiar idioma',
    },
    en: {
      'header.last_update_prefix': 'Last update: ',
      'header.settings_btn': 'Settings',
      'header.logout_btn': '⏏ Log out',
      'header.live_badge': '● LIVE',
      'alerts.title': '🔔 Alert history (24h)',
      'alerts.total': 'Total alerts',
      'alerts.high': 'HIGH alerts',
      'alerts.low': 'LOW alerts',
      'alerts.trend': 'Trend alerts',
      'readings.section_title': '📊 Current readings',
      'table.patient': 'Patient',
      'table.glucose': 'Glucose',
      'table.trend': 'Trend',
      'table.level': 'Level',
      'table.trend_alert': 'Trend alert',
      'table.last_reading': 'Last reading',
      'push.title': '🔔 Push notifications:',
      'push.activate': 'Enable notifications',
      'push.deactivate': 'Disable notifications',
      'push.no_support': 'Your browser does not support push notifications.',
      'push.blocked': '🔕 Notifications blocked in the browser.',
      'push.active': '✅ Notifications active on this device.',
      'push.activated': '✅ Notifications enabled!',
      'push.deactivated': '🔕 Notifications disabled.',
      'history.patient_label': 'Patient:',
      'history.patient_all': 'All',
      'history.hours_label': 'Last:',
      'history.6h': '6 hours',
      'history.24h': '24 hours',
      'history.48h': '48 hours',
      'history.7d': '7 days',
      'chart.by_hour': 'Alerts by hour',
      'chart.by_level': 'Level distribution',
      'chart.level_global': 'Level distribution — Global',
      'chart.level_patient': 'Level distribution — {0}',
      'chart.loading': '⏳ Loading…',
      'chart.no_data': 'Insufficient data',
      'history.section_title': 'Alert history',
      'history.table.time': 'Time',
      'history.table.patient': 'Patient',
      'history.table.glucose': 'Glucose',
      'history.table.level': 'Level',
      'history.table.message': 'Message',
      'glucose_charts.title': '📉 Glucose values in alerts',
      'footer.warning': '⚠️ This is not a medical device.',
      'footer.disclaimer': 'This tool is for informational reference only and does not replace professional medical care or the alarm systems of the glucose meter.',
      'no_data.loading': '⏳ Loading data…',
      'no_data.waiting': '📭 No data — waiting for readings…',
      'no_data.history_loading': '⏳ Loading history…',
      'no_data.history_empty': '📭 No alerts in the selected period.',
      'status.connected': 'Connected',
      'status.reconnecting': 'Reconnecting…',
      'status.disconnected': 'Disconnected',
      'status.connecting': 'Connecting…',
      'time.now': 'now',
      'time.min_ago': '{0} min ago',
      'time.hour_min_ago': '{0}h {1}m ago',
      'level.low': 'LOW',
      'level.high': 'HIGH',
      'level.normal': 'NORMAL',
      'trend.double_up': 'Rising very fast',
      'trend.single_up': 'Rising fast',
      'trend.forty_five_up': 'Rising',
      'trend.flat': 'Stable',
      'trend.forty_five_down': 'Falling',
      'trend.single_down': 'Falling fast',
      'trend.double_down': 'Falling very fast',
      'trend_alert.falling_fast': '🔻 Falling fast',
      'trend_alert.falling': '📉 Falling',
      'trend_alert.rising_fast': '🔺 Rising fast',
      'trend_alert.rising': '📈 Rising',
      'card.mg_dl': 'current mg/dL',
      'card.level': 'Level',
      'card.last_reading': 'Last reading',
      'card.trend_prefix': 'Trend: ',
      'card.stable_trend': 'Stable trend',
      'stats.max': 'max',
      'stats.avg': 'avg',
      'stats.min': 'min',
      'chart_label.low': 'Low',
      'chart_label.high': 'High',
      'chart_label.trend': 'Trend',
      'tir.high': 'High {0}%',
      'tir.range': '{0}% in range',
      'tir.low': 'Low {0}%',
      'zone.high': 'HIGH',
      'zone.low': 'LOW',
      'zone.range': 'IN RANGE',
      'alert_level.low': 'LOW',
      'alert_level.high': 'HIGH',
      'alert_level.trend': 'TREND',
      'lang.toggle': 'Change language',
    },
  };

  var SUPPORTED = ['es', 'en'];

  // ── Active locale (read once at module parse time for synchronous t() access)
  var _locale = (function () {
    try {
      var stored = localStorage.getItem('fgm_locale');
      return stored && SUPPORTED.indexOf(stored) !== -1 ? stored : 'es';
    } catch (e) {
      return 'es';
    }
  }());

  // ── translate ─────────────────────────────────────────────────────────────
  /** Look up a translation key.  {0}, {1}, … are replaced with positional args. */
  function t(key) {
    var dict = TRANSLATIONS[_locale] || TRANSLATIONS['es'];
    var str = (key in dict) ? dict[key] : (TRANSLATIONS['es'][key] !== undefined ? TRANSLATIONS['es'][key] : key);
    for (var i = 1; i < arguments.length; i++) {
      str = str.replace(new RegExp('\\{' + (i - 1) + '\\}', 'g'), String(arguments[i]));
    }
    return str;
  }

  // ── DOM application ────────────────────────────────────────────────────────
  function applyTranslations() {
    document.querySelectorAll('[data-i18n]').forEach(function (el) {
      var key = el.getAttribute('data-i18n');
      el.textContent = t(key);
    });
    document.documentElement.lang = _locale;
    _syncToggleBtn();
  }

  // ── Toggle button appearance ───────────────────────────────────────────────
  function _syncToggleBtn() {
    var btn = document.getElementById('lang-toggle-btn');
    if (!btn) return;
    var nextLabel = _locale === 'es' ? 'EN' : 'ES';
    btn.textContent = '🌐 ' + nextLabel;
    btn.title = t('lang.toggle');
    btn.setAttribute('aria-label', t('lang.toggle'));
  }

  // ── setLocale ─────────────────────────────────────────────────────────────
  function setLocale(locale) {
    if (SUPPORTED.indexOf(locale) === -1) return;
    _locale = locale;
    try { localStorage.setItem('fgm_locale', locale); } catch (e) { /* noop */ }
    applyTranslations();
    window.dispatchEvent(new CustomEvent('fgm:localechange', { detail: { locale: locale } }));
  }

  function getLocale() { return _locale; }

  // ── Wire up toggle button ─────────────────────────────────────────────────
  function _initToggle() {
    var btn = document.getElementById('lang-toggle-btn');
    if (!btn) return;
    btn.addEventListener('click', function () {
      setLocale(_locale === 'es' ? 'en' : 'es');
    });
    _syncToggleBtn();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      applyTranslations();
      _initToggle();
    });
  } else {
    applyTranslations();
    _initToggle();
  }

  // ── Public API ────────────────────────────────────────────────────────────
  window.i18n = { t: t, setLocale: setLocale, getLocale: getLocale, applyTranslations: applyTranslations };
}());
