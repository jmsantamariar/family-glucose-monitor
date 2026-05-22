# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- **Historial continuo de lecturas de glucosa** — `src/reading_history.py` persiste todas las lecturas en `reading_history.db` (SQLite). Ruta configurable con `reading_history_db` en `config.yaml`.
- **Endpoint `GET /api/patients/{id}/history?hours=N`** — devuelve lecturas del período indicado (1–8760 h ≈ 1 año). Aplica downsampling automático para rangos > 24 h (cubos de 15 min / 30 min / 1 h) para mantener la respuesta manejable.
- **Endpoint `GET /api/patients/{id}/history/export?format={csv|json}&days=N`** — exporta el historial completo a resolución nativa como archivo descargable. CSV con BOM (compatible Excel); JSON con envelope de metadatos. Ventana máxima: 365 días.
- **Endpoint `GET /api/patients/{id}/metrics?days=N`** — calcula métricas de control glucémico estándar: TIR (5 cubos: hipo severo/hipo/rango/hiper/hiper severo), GMI, CV y MAGE. Implementado en `src/analytics/glycemic_metrics.py`. Ventana por defecto: 14 días (mínimo clínico recomendado por el consenso internacional de TIR de 2019).
- **UI de análisis histórico en el dashboard** — selector de rango temporal, tarjeta de métricas glucémicas y botón de descarga CSV. Implementado en `src/dashboard/index.html`.
- **Modo Senior / Moderno** — toggle de accesibilidad disponible en todas las pantallas (dashboard, login, setup, configuración). Activa tipografía grande, alto contraste y elimina animaciones. Persiste en `localStorage` (`fgm-mode`; valores `senior` | `modern`). Controlado por el atributo `data-mode` en `<html>`.
- **Heurística de modo por defecto** — si no hay preferencia guardada, detecta `prefers-reduced-motion` + `prefers-color-scheme: light` para arrancar en modo `senior`; en caso contrario, `modern`.
- **i18n para el toggle de modo** — cadenas `es` y `en` añadidas para el botón senior/moderno.
- **Tema claro / oscuro** — toggle con persistencia en `localStorage` (`fgm-theme`; valores `light` | `dark`). Controlado por el atributo `data-theme` en `<html>`. Por defecto `light`.
- **Script anti-FOUC** — script inline en `<head>` que aplica `data-mode` y `data-theme` antes del primer render, evitando el flash de contenido sin estilo.
- **Rediseño visual del dashboard** — fuente Source Sans 3 (texto) + Source Serif 4 (display); paleta cálida; `<meta name="theme-color">` actualizado a `#3a2a20`.

### Changed

- **Service Worker `CACHE_NAME`** — actualizado a `fgm-shell-v3` (`src/dashboard/sw.js`) para invalidar cachés obsoletos tras el rediseño visual y los cambios de app-shell.
- **`/api/patients/{id}/history` límite de horas** — el parámetro `hours` pasa de un tope de 24 h a 8760 h (≈1 año).

### Fixed

- **Streaming de exportación CSV** — el endpoint `/history/export?format=csv` ahora genera el CSV en streaming fila a fila (`iter_readings()` + `StreamingResponse`) en lugar de construir el string completo en memoria.
- **Downsampling server-side de `/history`** — las respuestas para rangos > 24 h aplican downsampling en el servidor, reduciendo el tamaño del payload.
- **Claves `localStorage` unificadas** — todas las páginas usan el prefijo `fgm-` (`fgm-mode`, `fgm-theme`, `fgm-accent`).
- **Re-renderizado de sección histórica al cambiar locale** — la UI de análisis histórico se re-renderiza correctamente al cambiar el idioma.
- **Escape de nombres/IDs de paciente en HEADLINES y tarjetas** — previene XSS en el dashboard.
- **Sanitización de `patient_id` en `Content-Disposition`** — el nombre del archivo de exportación no puede contener caracteres que rompan la cabecera HTTP.

- **Notificaciones Web Push en el navegador** — El dashboard incluye un botón de suscripción/desuscripción para recibir alertas de glucosa como notificaciones del sistema. Funciona aunque la pestaña esté en segundo plano. Implementado con el patrón [StefanNedelchev/pwa-push-example](https://github.com/StefanNedelchev/pwa-push-example) adaptado a FastAPI/Python. (PR #45)
  - `src/push_subscriptions.py` — persistencia de suscripciones en `push_subscriptions.db` (SQLite, WAL, upsert por endpoint, limpieza automática de expiradas).
  - `src/outputs/webpush.py` — `WebPushOutput(BaseOutput)` que despacha a todos los navegadores suscritos vía `pywebpush` + VAPID. Las suscripciones expiradas (HTTP 404/410) se eliminan automáticamente.
  - `src/bootstrap.py` — `push_subscriptions.db` inicializado al arrancar junto a `alert_history.db`.
  - Tres nuevos endpoints en `src/api.py`: `GET /api/push/vapid-public-key` (libre), `POST /api/push/subscribe` (sesión + CSRF), `POST /api/push/unsubscribe` (sesión + CSRF).
  - `src/dashboard/sw.js` — Service Worker que gestiona eventos `push` (muestra notificación) y `notificationclick` (lleva al dashboard).
  - `src/dashboard/index.html` — Botón de suscripción con estado en vivo; `urlBase64ToUint8Array` para la clave VAPID.
  - `pywebpush==2.3.0` añadido como dependencia principal.
- **Gestión de claves VAPID** — `VAPID_PRIVATE_KEY` env var (PEM) > `vapid_private.pem` > auto-generación en primer arranque. `vapid_private.pem` en `.gitignore`. `.env.example` documenta el formato y el comando de generación.

### Security

- **API externa segura por defecto** — `api_server.py` ahora requiere `Authorization: Bearer <API_KEY>` en todos los endpoints. El modo sin autenticación solo está disponible con `ALLOW_INSECURE_LOCAL_API=1`. Sin `API_KEY` y sin ese flag, todas las peticiones son rechazadas con 401. Corrige comportamiento anterior donde la ausencia de `API_KEY` resultaba en acceso público.
- **`FGM_MASTER_KEY` via variable de entorno** — La clave maestra Fernet puede inyectarse con `FGM_MASTER_KEY` (hex 64 chars = 32 bytes). Prioridad: env var > archivo `.secret_key`. Recomendado para despliegues en Docker/Kubernetes.
- **Cookies de sesión endurecidas** — `HttpOnly`, `Secure` (en producción), `SameSite=Strict`, `path=/`, expiración 24h explícita.
- **Protección CSRF** — Patrón double-submit cookie (`csrf_token` cookie + `X-CSRF-Token` header) en todos los endpoints POST autenticados del dashboard. Exento solo en endpoints pre-autenticación (`/api/login`).
- **Validación de config antes de persistir** — `/api/setup` ejecuta `validate_config()` completo antes de escribir `config.yaml`. Retorna 422 con errores detallados si la configuración es inválida.
- **[CVE-2026-26007] Bump `cryptography` a `46.0.5`** — Mitiga subgroup attack en curvas SECT. Sin cambios de API.
- **Encriptación Fernet para credenciales LibreLinkUp** — Contraseñas almacenadas cifradas en `config.yaml`. Backward compatible con configs en texto plano. (PR #23)
- **Sesiones persistentes en SQLite** — Sesiones en `sessions.db`, no en memoria. (PR #21)
- **Autenticación separada para dashboard** — Credenciales dashboard independientes de LibreLinkUp, PBKDF2-HMAC-SHA256. (PR #13)
- **CORS restringido** — Orígenes configurables via `CORS_ALLOWED_ORIGINS`. (PR #13)
- **Permisos restrictivos en archivos sensibles** — `config.yaml` y `.secret_key` con permisos `0600`. (PR #23)

### Added

- **Migraciones de Base de Datos con Alembic** — Schema management para `alert_history.db`. Las migraciones no se aplican automáticamente; ejecuta `poetry run alembic upgrade head` desde el repo. `sessions.db` sigue usando DDL raw con `IF NOT EXISTS`.
- **`pyproject.toml` y `poetry.lock`** — Poetry es ahora el gestor de dependencias estándar del repositorio. `requirements.txt` y `requirements-dev.txt` se mantienen para compatibilidad con pip.
- **`.env.example`** — Plantilla documentada de todas las variables de entorno disponibles, con explicación de cada una y ejemplos de generación de secretos.
- **`src/setup_status.py`** — Módulo que determina si el setup está completo antes de arrancar. Expone `check_setup() → SetupStatus` e `is_setup_complete() → bool`. Usado por `main.py` para decidir entre modo normal y modo setup-only, y por `api.py` para redirigir al wizard.
- **`src/models/db_models.py`** — Modelos SQLAlchemy ORM (`SessionToken`, `LoginAttempt`, `AlertHistory`) que reflejan los esquemas físicos de SQLite. DDL sigue siendo raw SQL con `IF NOT EXISTS`.
- **Modelos de dominio tipados** (`src/models/__init__.py`) — `GlucoseReading`, `AlertsConfig`, `PatientState` como `dataclasses`. Contratos explícitos para datos que circulan por el sistema.
- **`src/db.py`** — Fábrica centralizada de conexiones SQLite con WAL, `foreign_keys=ON` y `timeout=10`. Todos los módulos usan `connect_db()` en lugar de `sqlite3.connect()` directo.
- **Dashboard web autenticado** — Panel web en tiempo real con semáforo de colores, login y wizard de setup. (PRs #6, #10, #12)
- **Alertas por tendencia** — Detección de falling/rising basada en flecha del sensor. (PR #6)
- **Historial de alertas SQLite** — Tabla `alerts` con índices. Limpieza automática configurable. (PR #9)
- **API REST externa** (`api_server.py`) — Ahora autenticada por defecto. (PR #3)
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

- **Arquitectura de caché simplificada** — `api.py` ya no hace polling independiente a LibreLinkUp. Lee del archivo compartido `readings_cache.json` con lazy reload basado en mtime. En modo `full`, `main.py` llama a `update_readings_cache()` para forzar invalidación ante escrituras del mismo segundo.
- **Dockerfile** — Usa Poetry como flujo principal (`poetry install --only main`). Mantiene compatibilidad con `requirements.txt`.
- **README.md** — Instrucciones de instalación con Poetry como opción principal. Sección de variables de entorno actualizada con `FGM_MASTER_KEY` y `API_KEY`. Sección de API externa actualizada con comportamiento seguro por defecto.
- **Documentación de modos de ejecución** — README actualizado con descripción clara de cada modo. (PR #15)
- **Extracción de módulo `outputs/`** — `build_outputs` extraído a paquete `outputs/` con módulos separados por canal. (PR #15)

### Fixed

- **Doble polling eliminado** — Modo `full` solo consulta LibreLinkUp desde `main.py`. (PR #19)
- **Uvicorn en hilo principal** — Manejo correcto de señales OS. (PR #19)
- **Caché unificada** — `api.py` lee `readings_cache.json` como fuente única. (PR #20)
- **Retry con exponential backoff** — LibreLinkUp con backoff exponencial configurable. (PR #22)
