# 👨‍👩‍👦 Family Glucose Monitor

![Tests](https://github.com/jmsantamariar/family-glucose-monitor/actions/workflows/tests.yml/badge.svg)
![License](https://img.shields.io/github/license/jmsantamariar/family-glucose-monitor)

> **⚠️ AVISO MÉDICO:** Este software NO es un dispositivo médico y NO reemplaza las alarmas del sensor CGM ni la atención profesional. Consulta [DISCLAIMER.md](DISCLAIMER.md) antes de usarlo.

Monitor de glucosa familiar para **padres y cuidadores** de personas con diabetes que usan sensores **FreeStyle Libre** con la app **LibreLinkUp**. Lee automáticamente las lecturas de *todos* los pacientes vinculados a la cuenta y envía alertas por Telegram, Webhook o WhatsApp Cloud API.

---

## ¿Para quién es?

Para **familias** donde uno o varios miembros usan un sensor FreeStyle Libre y tienen a un cuidador (padre, madre, pareja) configurado en LibreLinkUp. Este sistema centraliza las alertas de todos los pacientes en un único punto y ofrece un dashboard web en tiempo real.

---

## ✨ Características

- 📡 Lectura multi-paciente desde LibreLinkUp (todos los pacientes de la cuenta)
- 🌍 Soporte de 12 regiones de LibreLinkUp con auto-redirect
- ⚠️ Alertas configurables por umbral bajo/alto con cooldown anti-spam
- 📈 Alertas por tendencia (subiendo rápido, bajando rápido, etc.)
- 💬 Salidas: **Telegram**, **Webhook** (Pushover-compatible), **WhatsApp Cloud API**
- 🖥️ Dashboard web autenticado con semáforo de colores y gráficos por paciente
- 🔐 Autenticación con sesiones persistentes (SQLite) y contraseñas PBKDF2
- 🔒 Credenciales de LibreLinkUp encriptadas en disco (Fernet/AES-128-CBC + HMAC-SHA256)
- 📊 API REST externa autenticada para widgets, Home Assistant e integraciones locales
- 📋 Historial de alertas persistente (SQLite) con limpieza automática
- 🔄 Retry automático con exponential backoff para la API de LibreLinkUp
- 🔄 Modos: **cron** (una lectura), **daemon** (bucle continuo), **dashboard** (panel web), **full** (monitoreo + dashboard)
- 🗂️ Estado persistente por paciente con escritura atómica
- ✅ Validación de configuración al inicio con mensajes claros
- 🐳 Docker-ready
- 🧪 Tests unitarios con pytest

---

## 🚀 Quick Start

### 1. Clonar e instalar

#### Con Poetry (recomendado)

```bash
git clone https://github.com/jmsantamariar/family-glucose-monitor.git
cd family-glucose-monitor
pip install poetry          # instalar Poetry si no está disponible
poetry install              # instala dependencias de producción y desarrollo
```

#### Con pip (compatibilidad)

```bash
git clone https://github.com/jmsantamariar/family-glucose-monitor.git
cd family-glucose-monitor
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-dev.txt   # incluye sqlalchemy, alembic y utilidades de test
```

> **Nota pip:** `requirements.txt` usa `sqlalchemy>=2.0` (sin pinear) mientras que `requirements-dev.txt` instala `sqlalchemy==2.0.48` (versión fijada). **No mezcles pip y Poetry en el mismo entorno**: pueden producirse conflictos de versiones. Usa uno de los dos métodos de instalación de forma exclusiva.

### 2. Configurar variables de entorno (recomendado en producción)

```bash
cp .env.example .env
chmod 600 .env
# Edita .env con tus secretos (API_KEY, FGM_MASTER_KEY, etc.)
```

Las variables de entorno tienen **prioridad** sobre `config.yaml`. En producción se recomienda
inyectar los secretos críticos (`API_KEY`, `FGM_MASTER_KEY`) por variable de entorno o Docker secrets.
Consulta `.env.example` para la lista completa de variables disponibles.

### 3. Copiar y editar la configuración

```bash
cp config.example.yaml config.yaml
chmod 600 config.yaml
```

Edita `config.yaml` con tus credenciales:

```yaml
librelinkup:
  email: "tu-email@ejemplo.com"
  password: "tu-contraseña"
  region: "EU"          # US, EU, EU2, DE, FR, JP, AP, AU, AE, CA, LA, RU

alerts:
  low_threshold: 70
  high_threshold: 180
  cooldown_minutes: 20
  max_reading_age_minutes: 15

outputs:
  - type: telegram
    enabled: true
    bot_token: "123456:ABC..."
    chat_id: "-100123456789"
```

### 4. Validar la conexión

```bash
python validate_connection.py
python validate_telegram.py   # si usas Telegram
```

### 5. Ejecutar

```bash
python -m src.main
```

---

## 🏗️ Arquitectura

```
LibreLinkUp API (Abbott)
       │
       ▼
glucose_reader.py ──── lee TODOS los pacientes (con retry + backoff)
       │
       ▼
main.py ─── run_once() ─── evalúa umbrales y tendencias
       │                         │
       ├──► outputs/telegram.py  ──► Bot de Telegram
       ├──► outputs/webhook.py   ──► HTTP POST (Pushover)
       └──► outputs/whatsapp.py  ──► WhatsApp Cloud API
       │
       ├──► readings_cache.json (fuente única de verdad)
       │         │
       │         ├──► api.py (dashboard :8080) ── recarga por mtime desde archivo
       │         └──► api_server.py (API externa :8081) ── lectura directa por petición
       │
       └──► alert_history.db (SQLite)
                 │
                 └──► /api/alerts (ambos servidores)

Seguridad:
  config.yaml ──► credenciales LLU encriptadas (Fernet/HKDF-SHA256)
  .secret_key ──► clave maestra local (0600) — o FGM_MASTER_KEY en producción
  sessions.db ──► sesiones persistentes (SQLite)
  dashboard_auth ──► contraseñas PBKDF2-HMAC-SHA256
```

Para el diagrama completo y decisiones de diseño, consulta [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

### Modos de ejecución

| Modo | Descripción | Polling LibreLinkUp | Ciclo de alertas | Dashboard |
|------|-------------|---------------------|------------------|-----------|
| `cron` | Una sola lectura y salida (default) | ✅ una vez | ✅ una vez | ❌ |
| `daemon` | Bucle continuo en foreground | ✅ continuo | ✅ continuo | ❌ |
| `dashboard` | Panel web; hace polling sin ciclo de alertas/salidas | ✅ background | ❌ | ✅ |
| `full` | Polling + ciclo de alertas + panel web | ✅ background | ✅ background | ✅ |

En modo `full`, Uvicorn se ejecuta en el hilo principal (manejo correcto de señales) y el polling corre en un hilo daemon en segundo plano. Solo hay **un** ciclo de polling activo.

---

## 🔐 Seguridad

| Mecanismo | Descripción |
|-----------|-------------|
| **Encriptación de credenciales** | Contraseña de LibreLinkUp almacenada con Fernet (AES-128-CBC + HMAC-SHA256); clave maestra derivada con HKDF-SHA256. Almacenada en `config.yaml`. Backward compatible con texto plano. |
| **Hashing de contraseñas** | Contraseña del dashboard hasheada con PBKDF2-HMAC-SHA256 (260,000 iteraciones). |
| **Sesiones persistentes** | Tokens de sesión almacenados en SQLite (`sessions.db`) con TTL de 24 horas. |
| **Permisos de archivos** | `config.yaml` y `.secret_key` con permisos `0600` (solo propietario). |
| **CORS restringido** | API externa sin orígenes permitidos por defecto. Configurable via `CORS_ALLOWED_ORIGINS`. |
| **CSRF** | Patrón double-submit cookie (`csrf_token` + `X-CSRF-Token`) en todos los endpoints POST autenticados del dashboard. |
| **API segura por defecto** | La API externa requiere `Authorization: Bearer <API_KEY>`. Sin `API_KEY` configurada y sin `ALLOW_INSECURE_LOCAL_API=1`, todas las peticiones son rechazadas con 401. |
| **Separación de credenciales** | Credenciales de LibreLinkUp independientes de las del dashboard. |

> ⚠️ Para reportar vulnerabilidades, consulta [SECURITY.md](SECURITY.md).

### Estructura de archivos

```
config.yaml              ← credenciales y umbrales (nunca en git)
src/
  main.py                ← orquestador principal (modos: cron, daemon, dashboard, full)
  config_schema.py       ← validación de configuración
  glucose_reader.py      ← lee TODOS los pacientes vía pylibrelinkup
  alert_engine.py        ← evalúa umbrales, cooldown, construye mensajes
  state.py               ← persistencia JSON por patient_id (escritura atómica)
  api.py                 ← dashboard web + API interna autenticada (modo dashboard/full)
  api_server.py          ← API REST externa autenticada de solo lectura (para widgets/apps)
  auth.py                ← gestión de sesiones y credenciales del dashboard
  alert_history.py       ← historial de alertas en SQLite (via SQLAlchemy ORM)
  crypto.py              ← cifrado/descifrado Fernet para credenciales sensibles
  db.py                  ← fábrica centralizada de conexiones SQLite (WAL, FK, timeout)
  setup_status.py        ← detección de setup completo vs. modo wizard inicial
  models/
    __init__.py          ← dataclasses de dominio: GlucoseReading, AlertsConfig, PatientState
    db_models.py         ← modelos SQLAlchemy ORM: SessionToken, LoginAttempt, AlertHistory
  outputs/
    base.py              ← clase abstracta BaseOutput / interfaz Notifier
    __init__.py          ← fábrica build_outputs() y MultiNotifier
    telegram.py          ← Bot API de Telegram
    webhook.py           ← Webhook HTTP (Pushover-compatible)
    whatsapp.py          ← WhatsApp Cloud API
  dashboard/
    index.html           ← interfaz principal del dashboard (SPA)
    login.html           ← página de login
    setup.html           ← wizard de configuración inicial
tests/
  conftest.py
  test_alert_engine.py
  test_alert_history.py
  test_alembic_migrations.py
  test_api.py
  test_api_server.py
  test_auth.py
  test_config_schema.py
  test_crypto.py
  test_db_models.py
  test_glucose_reader.py
  test_main_startup.py
  test_multi_notifier.py
  test_run_once.py
  test_setup_status.py
  test_state.py
  test_telegram_output.py
  test_trend_alerts.py
docs/
  ARCHITECTURE.md        ← diseño del sistema
  DEPLOYMENT.md          ← guía de despliegue y operación
  PRIVACY.md             ← privacidad de datos de salud
validate_connection.py   ← prueba la conexión a LibreLinkUp
validate_telegram.py     ← prueba el bot de Telegram
```

---

## 📬 Ejemplo de alerta en Telegram

Cuando la glucosa de un paciente sale del rango, recibirás en Telegram:

```
⚠️ Mamá: glucosa en 55 mg/dL ↓ — BAJA
```

```
⚠️ Juan: glucosa en 250 mg/dL ↑ — ALTA
```

Los mensajes incluyen el nombre del paciente, el valor, la flecha de tendencia y el nivel de alerta. Puedes personalizar el formato en `config.yaml` bajo `alerts.messages`.

---

## ⚙️ Configuración completa

### Variables de entorno (recomendado para producción/Docker)

Copia `.env.example` a `.env` y ajusta los valores. Consulta ese archivo para la lista completa.
Las variables de entorno tienen **prioridad sobre `config.yaml`** — úsalas para secretos críticos en producción.

```bash
# Secretos de producción (requeridos en producción)
export FGM_MASTER_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
export API_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"

# Credenciales LibreLinkUp (alternativa a config.yaml)
export LIBRELINKUP_EMAIL="tu-email@ejemplo.com"
export LIBRELINKUP_PASSWORD="tu-contraseña"

# Opcional
export WHATSAPP_ACCESS_TOKEN="token_whatsapp"
```

### Telegram — configuración del bot

1. Habla con [@BotFather](https://t.me/BotFather) → `/newbot` → copia el token.
2. Obtén tu `chat_id`: abre `https://api.telegram.org/bot<TOKEN>/getUpdates` después de enviar un mensaje al bot.
3. Configura en `config.yaml` y valida con `python validate_telegram.py`.

### Modo daemon (bucle continuo)

```yaml
monitoring:
  mode: "daemon"
  interval_seconds: 300   # cada 5 minutos
```

---

## ▶️ Ejecución

El modo de ejecución se configura con `monitoring.mode` en `config.yaml`. Hay cuatro modos disponibles:

| Modo | Descripción | Polling LibreLinkUp | Ciclo de alertas | Dashboard |
|------|-------------|---------------------|------------------|-----------|
| `cron` | Una sola lectura y salida (default) | ✅ una vez | ✅ una vez | ❌ |
| `daemon` | Bucle continuo en foreground | ✅ continuo | ✅ continuo | ❌ |
| `dashboard` | Panel web; hace polling sin ciclo de alertas/salidas | ✅ background | ❌ | ✅ |
| `full` | Polling + ciclo de alertas + panel web | ✅ background | ✅ background | ✅ |

### Modo cron (una sola lectura)

```yaml
monitoring:
  mode: "cron"
```

```bash
python -m src.main
```

Agrega al crontab para ejecución periódica:
```
*/5 * * * * cd /ruta/proyecto && .venv/bin/python -m src.main >> /var/log/glucose.log 2>&1
```

### Modo daemon (bucle continuo)

```yaml
monitoring:
  mode: "daemon"
  interval_seconds: 300
```

```bash
python -m src.main
```

### Modo dashboard (panel web)

```yaml
monitoring:
  mode: "dashboard"

dashboard:
  host: "0.0.0.0"
  port: 8080
```

```bash
python -m src.main
# Panel disponible en http://localhost:8080
```

### Modo full (monitoreo + dashboard)

```yaml
monitoring:
  mode: "full"
  interval_seconds: 300

dashboard:
  host: "0.0.0.0"
  port: 8080
```

```bash
python -m src.main
# Dashboard en http://localhost:8080 + ciclos de monitoreo cada 5 minutos
```

### Docker

```bash
docker build -t family-glucose-monitor .
docker run --rm \
  -e FGM_MASTER_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')" \
  -e API_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')" \
  -v $(pwd)/config.yaml:/app/config.yaml:ro \
  -v $(pwd)/state.json:/app/state.json \
  -v $(pwd)/alert_history.db:/app/alert_history.db \
  -v $(pwd)/sessions.db:/app/sessions.db \
  -v $(pwd)/readings_cache.json:/app/readings_cache.json \
  -p 8080:8080 \
  family-glucose-monitor
```

> **Nota:** El Dockerfile expone el puerto 8080 y arranca con `python -m src.main`. Para el modo `full` o `dashboard`, asegúrate de que `monitoring.mode` esté configurado correctamente en `config.yaml`.

---

## 🌐 API REST externa

El sistema incluye un servidor de API ligero (`src/api_server.py`) para que clientes externos (widgets Android, complicaciones de Apple Watch, dashboards remotos) consuman las últimas lecturas de glucosa sin autenticarse contra el dashboard.

> **Distinción importante:** `src/api.py` es el backend del dashboard web (requiere login de sesión). `src/api_server.py` es la API externa autenticada de solo lectura. Son dos servidores independientes con propósitos distintos.

> **Seguridad por defecto:** La API externa requiere `Authorization: Bearer <API_KEY>`. Si `API_KEY` no está definida **y** `ALLOW_INSECURE_LOCAL_API=1` no está activo, todas las peticiones son rechazadas con **401**. Para entornos locales/dev sin autenticación, establece `ALLOW_INSECURE_LOCAL_API=1` (nunca en producción).

### Cómo funciona

El proceso de monitoreo principal (`src/main.py`) escribe `readings_cache.json` al final de cada ciclo. La API externa lee ese archivo en cada petición, sin hacer llamadas directas a LibreLinkUp.

```
python -m src.main         ←→  escribe readings_cache.json
                                           ↓
uvicorn src.api_server:app ←→  lee readings_cache.json → responde clientes
```

### Habilitar la API externa

```bash
# Junto al monitor (terminal separada o proceso independiente):
export API_KEY="tu-clave-secreta"
uvicorn src.api_server:app --host 0.0.0.0 --port 8081
```

Con Docker:

```bash
docker run --rm \
  -e API_KEY="tu-clave-secreta" \
  -v $(pwd)/readings_cache.json:/app/readings_cache.json \
  -v $(pwd)/alert_history.db:/app/alert_history.db \
  -p 8081:8081 \
  family-glucose-monitor \
  uvicorn src.api_server:app --host 0.0.0.0 --port 8081
```

### Endpoints de la API externa

| Method | Path | Descripción |
|--------|------|-------------|
| `GET` | `/api/readings` | Todas las lecturas cacheadas de los pacientes |
| `GET` | `/api/readings/{patient_id}` | Lectura de un paciente específico por ID |
| `GET` | `/api/health` | Health de la API + frescura del caché |
| `GET` | `/api/alerts` | Historial de alertas (últimas 24h por defecto, máx. 168h) |

Todos los endpoints requieren `Authorization: Bearer <API_KEY>`.

#### `GET /api/readings`

```json
{
  "readings": [
    {
      "patient_id": "abc-123",
      "patient_name": "Juan García",
      "value": 120,
      "timestamp": "2026-01-01T10:00:00+00:00",
      "trend_arrow": "→",
      "trend_name": "stable",
      "is_high": false,
      "is_low": false
    }
  ],
  "updated_at": "2026-01-01T10:05:00+00:00"
}
```

#### `GET /api/readings/{patient_id}`

Devuelve el objeto de lectura para el paciente indicado, o `404` si no se encuentra.

#### `GET /api/health`

```json
{
  "status": "ok",
  "patient_count": 3,
  "updated_at": "2026-01-01T10:05:00+00:00",
  "cache_age_seconds": 42.5
}
```

#### `GET /api/alerts`

Parámetros opcionales: `patient_id` (filtro) y `hours` (rango, 1–168, defecto 24).

### Sección `api` en `config.yaml`

```yaml
api:
  enabled: false          # reservado para integración futura de auto-inicio
  host: "0.0.0.0"
  port: 8081
  cache_file: "readings_cache.json"
```

> **Nota:** `api.cache_file` configura la ruta donde `src/main.py` escribe el caché. `src/api_server.py` siempre lee desde la ruta resuelta relativa al directorio raíz del proyecto, independientemente de esta configuración.

Para una guía completa de despliegue incluyendo HTTPS, reverse proxy y configuración de producción, consulta [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

---

## 🖥️ Dashboard

El sistema incluye un dashboard web en tiempo real que muestra el estado de todos los pacientes monitoreados. Sirve desde `src/dashboard/` (HTML/JS) a través de `src/api.py`.

### Características del Dashboard

- **Vista multi-paciente**: Tarjetas con lectura actual, tendencia y tiempo desde última lectura
- **Código de colores semáforo**: Verde (normal), Amarillo (precaución), Rojo (alerta)
- **Gráficas de alertas por hora**: Histograma apilado por paciente (últimas 24h)
- **Distribución por nivel**: Gráfica de dona mostrando proporción bajo/normal/alto
- **Valores de glucosa en alertas**: Gráfica de línea por paciente con zonas de rango
- **Filtros**: Por paciente y por período de tiempo
- **Modo oscuro**: Adaptación automática al tema del sistema
- **Auto-actualización**: Los datos se refrescan automáticamente

### Ejecutar el Dashboard

```bash
# Modo solo dashboard (polling a LibreLinkUp en background, sin envío de alertas)
# En config.yaml: monitoring.mode: "dashboard"
python -m src.main

# Modo completo (polling + ciclo de alertas + dashboard en paralelo)
# En config.yaml: monitoring.mode: "full"
python -m src.main
```

El dashboard estará disponible en `http://localhost:8080` por defecto.

> **Nota de seguridad:** El dashboard requiere autenticación. El proceso de setup inicial (`/setup`) te pedirá crear credenciales. Para producción, consulta [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

---

## 🧪 Tests

```bash
# Con Poetry (recomendado)
poetry install   # instala también dependencias de desarrollo
poetry run pytest tests/ -v --cov=src

# Con pip
pip install -r requirements.txt
pip install -r requirements-dev.txt
pytest tests/ -v --cov=src
```

---

## 🗄️ Migraciones de Base de Datos

El sistema usa [Alembic](https://alembic.sqlalchemy.org/) para gestionar el esquema de `alert_history.db`. Las migraciones se aplican automáticamente al arrancar la aplicación en condiciones normales, pero en despliegues donde el contenedor no tiene acceso de escritura al directorio de datos hasta que se monten los volúmenes, puede ser necesario ejecutarlas manualmente:

```bash
# Aplicar todas las migraciones pendientes
alembic upgrade head

# Ver el estado actual de la base de datos
alembic current

# Ver el historial de migraciones
alembic history
```

> **Nota:** `sessions.db` no está gestionada por Alembic. Su esquema se crea con DDL raw (`IF NOT EXISTS`) al arrancar `src/auth.py`. Si necesitas regenerarlo, borra el archivo y reinicia la aplicación.

---

## ⚠️ Limitaciones

- **No es un dispositivo médico.** No está certificado por ninguna autoridad sanitaria.
- **Depende de LibreLinkUp.** Si la API de Abbott no está disponible, no habrá lecturas.
- **No almacena histórico completo de glucosa.** Persiste el estado de la última alerta por paciente (`state.json`) y un historial de alertas enviadas (`alert_history.db`). No guarda el historial continuo de lecturas de glucosa.
- **No garantiza entrega en tiempo real.** Pueden ocurrir retrasos por red, API o servicios de mensajería.
- **No reemplaza las alarmas del sensor.** Las alarmas del FreeStyle Libre son el mecanismo primario.
- **API no oficial.** LibreLinkUp no provee una API pública documentada; puede cambiar sin aviso.
- **File locking vía `fcntl`.** Solo disponible en Linux/macOS. En Windows el lock se omite silenciosamente.

---

## 🔒 Seguridad y privacidad

- `config.yaml` está en `.gitignore` — **nunca** lo subas al repositorio.
- Usa `chmod 600 config.yaml` para restringir el acceso.
- Para producción, usa variables de entorno en lugar de secretos en `config.yaml`.
- **No expongas el dashboard ni la API sin HTTPS** en producción — consulta [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).
- Consulta [SECURITY.md](SECURITY.md) para la política de seguridad completa.
- Consulta [docs/PRIVACY.md](docs/PRIVACY.md) para información sobre privacidad de datos.

---

## 📦 Créditos

- [robberwick/pylibrelinkup](https://github.com/robberwick/pylibrelinkup) — cliente Python para LibreLinkUp
- [rreal/glucose-actions](https://github.com/rreal/glucose-actions) — arquitectura de alertas
- [DiaKEM/libre-link-up-api-client](https://github.com/DiaKEM/libre-link-up-api-client) — referencia de la API

---

> **⚠️ AVISO MÉDICO FINAL:** Este software NO es un dispositivo médico. NO reemplaza las alarmas del sensor CGM ni la atención profesional. El usuario asume toda la responsabilidad. Consulta [DISCLAIMER.md](DISCLAIMER.md).