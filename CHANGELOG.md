# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Security
- **[CVE-2026-26007] Bump `cryptography` a `46.0.5`** — Se actualiza la dependencia `cryptography` de `44.0.2` a `46.0.5` para mitigar CVE-2026-26007 (subgroup attack en curvas SECT por falta de validación de subgrupos). Versiones afectadas: ≤ 46.0.4. Sin cambios de API; totalmente compatible con el resto de dependencias.
- **Encriptación Fernet para credenciales LibreLinkUp** — Las contraseñas de LibreLinkUp ahora se almacenan encriptadas (AES-128-CBC + HMAC-SHA256) en `config.yaml` usando `cryptography.fernet.Fernet`. La clave se almacena en `.secret_key` con permisos `0600`. Backward compatible con configs en texto plano existentes. (PR #23)
- **Sesiones persistentes en SQLite** — Las sesiones de usuario se almacenan en `sessions.db` en lugar de un diccionario in-memory, sobreviviendo reinicios y soportando múltiples workers. (PR #21)
- **Autenticación separada para dashboard** — Las credenciales del dashboard (`dashboard_auth`) son independientes de las de LibreLinkUp. Contraseñas hasheadas con PBKDF2-HMAC-SHA256 (260,000 iteraciones, OWASP 2023). (PR #13)
- **CORS restringido** — `api_server.py` ahora restringe CORS por defecto; orígenes configurables via `CORS_ALLOWED_ORIGINS`. (PR #13)
- **Permisos restrictivos en archivos sensibles** — `config.yaml` y `.secret_key` se crean con permisos `0600` (solo lectura/escritura del propietario). (PR #23)

### Fixed
- **Doble polling eliminado** — En modo `full`, solo `main.py` consulta la API de LibreLinkUp. El `_poll_loop` de `api.py` se suprime via `set_external_polling(True)`, previniendo peticiones duplicadas y posible rate-limiting/ban. (PR #19)
- **Uvicorn en hilo principal** — `uvicorn.run()` ahora se ejecuta en el hilo principal para manejar señales OS (SIGINT/SIGTERM) correctamente. El bucle de polling se mueve a un hilo daemon en segundo plano. (PR #19)
- **Caché unificada** — `api.py` (dashboard) ahora lee de `readings_cache.json` como fuente única de verdad (igual que `api_server.py`), eliminando la divergencia de datos entre las dos interfaces. Usa detección de cambios por `mtime` para recarga eficiente. (PR #20)
- **Retry con exponential backoff** — `glucose_reader.py` ahora reintenta automáticamente las peticiones a LibreLinkUp con backoff exponencial (base 2s, máx 60s) y jitter aleatorio ±25%. Configurable via `config.yaml` (`librelinkup.retry`). `RedirectError` se excluye de reintentos. (PR #22)
- **Lookup de templates de trend alerts** — `build_message()` alineada con el schema de `config.example.yaml`. (PR #8)
- **Validación de auth del dashboard** — Corrección de validación y consistencia en la UI de login. (PR #16)

### Added
- **Dashboard web autenticado** — Panel web en tiempo real con semáforo de colores (rojo/amarillo/verde), login y wizard de setup. Rutas protegidas con middleware de sesión. (PRs #6, #10, #12)
- **Alertas por tendencia** — Detección de `falling_fast`, `falling`, `rising_fast`, `rising` basada en la flecha de tendencia del sensor y umbrales configurables. (PR #6)
- **Historial de alertas SQLite** — Tabla `alerts` con índices para consultas por timestamp y paciente. Endpoints `/api/alerts` en ambos servidores. Limpieza automática configurable (`alert_history_max_days`). (PR #9)
- **Gráficos por paciente** — Barras apiladas de pacientes y gráficos de línea de glucosa en el dashboard. (PR #10)
- **API REST externa** (`api_server.py`) — API read-only sin autenticación en puerto separado (default 8081) para widgets, Home Assistant, etc. Endpoints: `/api/readings`, `/api/readings/{patient_id}`, `/api/health`, `/api/alerts`. (PR #3)
- **Módulo de salidas** (`outputs/`) — Soporte para Telegram, Webhook (Pushover-compatible), y WhatsApp Cloud API como canales de notificación. (PRs #1, #15)
- **Validación de configuración** — Schema validation al inicio con mensajes claros de error. (PR #5)
- **CI con GitHub Actions** — Workflow de tests automatizados con pytest. (PR #5)
- **Política de seguridad** — `SECURITY.md` con proceso de reporte de vulnerabilidades. (PR #5)
- **Multi-paciente** — Lectura automática de todos los pacientes vinculados a la cuenta LibreLinkUp. (PR #1)
- **Estado persistente** — Archivo `state.json` con escritura atómica para tracking de cooldowns por paciente. (PR #1)
- **Modos de ejecución** — `cron` (una lectura), `daemon` (bucle continuo), `dashboard` (panel web), `full` (monitoreo + dashboard). (PRs #1, #6)
- **Docker ready** — `Dockerfile` con imagen basada en `python:3.12-slim`. (PR #1)
- **Soporte multi-región** — 12 regiones de LibreLinkUp soportadas (US, EU, EU2, DE, FR, JP, AP, AU, AE, CA, LA, RU) con auto-redirect. (PR #1)

### Changed
- **Arquitectura de caché simplificada** — `api.py` ya no mantiene su propio diccionario in-memory con polling independiente. Lee del archivo compartido `readings_cache.json` con lazy reload basado en mtime. (PR #20)
- **Documentación de modos de ejecución** — README actualizado con descripción clara de cada modo. (PR #15)
- **Extracción de módulo `outputs/`** — `build_outputs` extraído a paquete `outputs/` con módulos separados por canal. (PR #15)
