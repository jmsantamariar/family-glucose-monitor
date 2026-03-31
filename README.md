# 👨‍👩‍👦 Family Glucose Monitor

![Tests](https://github.com/jmsantamariar/family-glucose-monitor/actions/workflows/tests.yml/badge.svg)
![License](https://img.shields.io/github/license/jmsantamariar/family-glucose-monitor)

> **⚠️ AVISO MÉDICO:** Este software NO es un dispositivo médico y NO reemplaza las alarmas del sensor CGM ni la atención profesional. Consulta [DISCLAIMER.md](DISCLAIMER.md) antes de usarlo.

Monitor de glucosa familiar para **padres y cuidadores** de personas con diabetes que usan sensores **FreeStyle Libre** con la app **LibreLinkUp**. Lee automáticamente las lecturas de *todos* los pacientes vinculados a tu cuenta y envía alertas por Telegram, Webhook o WhatsApp cuando los valores salen del rango configurado.

---

## ¿Para quién es?

Para **familias** donde uno o varios miembros usan un sensor FreeStyle Libre y tienen a un cuidador (padre, madre, pareja) configurado en LibreLinkUp. Este sistema centraliza las alertas de todos los pacientes en tus canales de comunicación favoritos.

---

## ✨ Características

- 📡 Lectura multi-paciente desde LibreLinkUp (todos los pacientes de la cuenta)
- ⚠️ Alertas configurables por umbral bajo/alto con cooldown anti-spam
- 💬 Salidas: **Telegram**, **Webhook** (Pushover-compatible), **WhatsApp Cloud API**
- 🔄 Modos: **cron** (una lectura) o **daemon** (bucle continuo)
- 🗂️ Estado persistente por paciente con escritura atómica
- ✅ Validación de configuración al inicio con mensajes claros
- 🐳 Docker-ready
- 🧪 Tests unitarios con pytest

---

## 🚀 Quick Start

### 1. Clonar e instalar

```bash
git clone https://github.com/jmsantamariar/family-glucose-monitor.git
cd family-glucose-monitor
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Copiar y editar la configuración

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

### 3. Validar la conexión

```bash
python validate_connection.py
python validate_telegram.py   # si usas Telegram
```

### 4. Ejecutar

```bash
python -m src.main
```

---

## 🏗️ Arquitectura

```
LibreLinkUp API
      │
      ▼
glucose_reader.py ──── lee TODOS los pacientes
      │
      ▼
alert_engine.py ─────── evalúa umbrales, cooldown, stale
      │
      ├──► outputs/telegram.py   ──► Bot de Telegram
      ├──► outputs/webhook.py    ──► HTTP POST (Pushover)
      └──► outputs/whatsapp.py   ──► WhatsApp Cloud API
      │
      ▼
state.py ───────────── persiste estado por patient_id (state.json)
```

Para el diagrama completo y decisiones de diseño, consulta [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

### Estructura de archivos

```
config.yaml              ← credenciales y umbrales (nunca en git)
src/
  main.py                ← orquestador principal
  config_schema.py       ← validación de configuración
  glucose_reader.py      ← lee TODOS los pacientes vía pylibrelinkup
  alert_engine.py        ← evalúa umbrales, cooldown, construye mensajes
  state.py               ← persistencia JSON por patient_id
  outputs/
    base.py              ← clase abstracta BaseOutput
    telegram.py          ← Bot API de Telegram
    webhook.py           ← Webhook HTTP (Pushover-compatible)
    whatsapp.py          ← WhatsApp Cloud API
tests/
  test_alert_engine.py
  test_state.py
  test_telegram_output.py
docs/
  ARCHITECTURE.md        ← diseño del sistema
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

```bash
export LIBRELINKUP_EMAIL="tu-email@ejemplo.com"
export LIBRELINKUP_PASSWORD="tu-contraseña"
export WHATSAPP_ACCESS_TOKEN="token_whatsapp"  # opcional
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

### Modo cron (una sola lectura)

```bash
python -m src.main
```

Agrega al crontab:
```
*/5 * * * * cd /ruta/proyecto && .venv/bin/python -m src.main >> /var/log/glucose.log 2>&1
```

### Docker

```bash
docker build -t family-glucose-monitor .
docker run --rm \
  -v $(pwd)/config.yaml:/app/config.yaml:ro \
  -v $(pwd)/state.json:/app/state.json \
  family-glucose-monitor
```

---

## 🌐 REST API

The monitoring system can expose a lightweight HTTP API so that external clients (Android widgets, Apple Watch complications, web dashboards) can consume the latest glucose readings.

### Enable the API server

Start the API server alongside the monitor:

```bash
uvicorn src.api_server:app --host 0.0.0.0 --port 8080
```

Or with Docker (port 8080 is already exposed):

```bash
docker run --rm \
  -v $(pwd)/config.yaml:/app/config.yaml:ro \
  -v $(pwd)/readings_cache.json:/app/readings_cache.json \
  -p 8080:8080 \
  family-glucose-monitor \
  uvicorn src.api_server:app --host 0.0.0.0 --port 8080
```

The monitor loop writes `readings_cache.json` after every cycle; the API server reads from this file.

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/readings` | All cached patient readings |
| `GET` | `/api/readings/{patient_id}` | Single patient reading by ID |
| `GET` | `/api/health` | API health + data freshness |

#### `GET /api/readings`

```json
{
  "readings": [
    {
      "patient_id": "abc-123",
      "patient_name": "Juan García",
      "value": 120,
      "timestamp": "2026-01-01T10:00:00+00:00",
      "trend_name": "Flat",
      "trend_arrow": "→",
      "is_high": false,
      "is_low": false
    }
  ],
  "updated_at": "2026-01-01T10:05:00+00:00"
}
```

#### `GET /api/readings/{patient_id}`

Returns the reading object for the given patient ID, or `404` if not found.

#### `GET /api/health`

```json
{
  "status": "ok",
  "patient_count": 3,
  "updated_at": "2026-01-01T10:05:00+00:00",
  "cache_age_seconds": 42.5
}
```

### `config.yaml` API section

```yaml
api:
  enabled: false          # reserved for future auto-start integration
  host: "0.0.0.0"
  port: 8080
  cache_file: "readings_cache.json"
```

---

## 🖥️ Dashboard

El sistema incluye un dashboard web en tiempo real que muestra el estado de todos los pacientes monitoreados.

### Características del Dashboard

- **Vista multi-paciente**: Tarjetas con lectura actual, tendencia y tiempo desde última lectura
- **Código de colores semáforo**: Verde (normal), Amarillo (precaución), Rojo (alerta)
- **Gráficas de alertas por hora**: Histograma apilado por paciente (últimas 24h)
- **Distribución por nivel**: Gráfica de dona mostrando proporción bajo/normal/alto
- **Valores de glucosa en alertas**: Gráfica de línea por paciente con zonas de rango
- **Filtros**: Por paciente y por período de tiempo
- **Modo oscuro**: Adaptación automática al tema del sistema
- **Auto-actualización**: Los datos se refrescan automáticamente

### Mockup del Dashboard

![Dashboard Mockup](docs/images/dashboard-mockup.png)

> **Nota**: Este mockup muestra las mejoras planificadas para el dashboard. La versión actual ya incluye la tabla de pacientes en tiempo real con código de colores.

### Ejecutar el Dashboard

```bash
# Modo solo dashboard
# En config.yaml, establece monitoring.mode: "dashboard"
python -m src.main

# Modo completo (monitoreo + dashboard)
# En config.yaml, establece monitoring.mode: "full"
python -m src.main
```

El dashboard estará disponible en `http://localhost:8080` por defecto.

---

## 🧪 Tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v --cov=src
```

---

## ⚠️ Limitaciones

- **No es un dispositivo médico.** No está certificado por ninguna autoridad sanitaria.
- **Depende de LibreLinkUp.** Si la API de Abbott no está disponible, no habrá lecturas.
- **No almacena histórico.** Solo persiste el estado de la última alerta por paciente.
- **No garantiza entrega en tiempo real.** Pueden ocurrir retrasos por red, API o servicios de mensajería.
- **No reemplaza las alarmas del sensor.** Las alarmas del FreeStyle Libre son el mecanismo primario.
- **API no oficial.** LibreLinkUp no provee una API pública documentada; puede cambiar sin aviso.

---

## 🔒 Seguridad y privacidad

- `config.yaml` está en `.gitignore` — **nunca** lo subas al repositorio.
- Usa `chmod 600 config.yaml` para restringir el acceso.
- Para producción, usa variables de entorno en lugar de `config.yaml`.
- Consulta [SECURITY.md](SECURITY.md) para la política de seguridad completa.
- Consulta [docs/PRIVACY.md](docs/PRIVACY.md) para información sobre privacidad de datos.

---

## 📦 Créditos

- [robberwick/pylibrelinkup](https://github.com/robberwick/pylibrelinkup) — cliente Python para LibreLinkUp
- [rreal/glucose-actions](https://github.com/rreal/glucose-actions) — arquitectura de alertas
- [DiaKEM/libre-link-up-api-client](https://github.com/DiaKEM/libre-link-up-api-client) — referencia de la API

---

> **⚠️ AVISO MÉDICO FINAL:** Este software NO es un dispositivo médico. NO reemplaza las alarmas del sensor CGM ni la atención profesional. El usuario asume toda la responsabilidad. Consulta [DISCLAIMER.md](DISCLAIMER.md).
