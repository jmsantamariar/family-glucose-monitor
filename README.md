# 👨‍👩‍👦 Family Glucose Monitor

Monitor de glucosa familiar basado en LibreLinkUp — lee **todos los pacientes** de la cuenta y envía alertas por Telegram, Webhook o WhatsApp cuando los valores salen del rango configurado.

---

## ✨ Características

- 📡 Lectura multi-paciente desde LibreLinkUp (yo, mamá, papá… todos en la misma cuenta)
- ⚠️ Alertas configurables por umbral bajo y alto con cooldown para evitar spam
- 💬 Salidas: **Telegram**, **Webhook** (Pushover-compatible), **WhatsApp Cloud API**
- 🔄 Modos de ejecución: **cron** (una vez) o **daemon** (bucle con intervalo)
- 🗂️ Estado persistente por paciente (JSON) con escritura atómica
- 🐳 Docker-ready
- ✅ Tests unitarios con pytest

---

## 🏗️ Arquitectura

```
config.yaml          ← credenciales y umbrales (nunca en git)
src/
  main.py            ← orquestador principal
  glucose_reader.py  ← lee TODOS los pacientes vía pylibrelinkup
  alert_engine.py    ← evalúa umbrales, cooldown, construye mensajes
  state.py           ← persistencia JSON por patient_id
  outputs/
    base.py          ← clase abstracta BaseOutput
    telegram.py      ← Bot API de Telegram
    webhook.py       ← Webhook HTTP (Pushover-compatible)
    whatsapp.py      ← WhatsApp Cloud API
tests/
  test_alert_engine.py
  test_state.py
  test_telegram_output.py
validate_connection.py  ← prueba la conexión a LibreLinkUp
validate_telegram.py    ← prueba el bot de Telegram
```

---

## 📋 Requisitos

- Python 3.12+
- Cuenta en [LibreLinkUp](https://www.librelinkup.com/) con los pacientes vinculados
- (Opcional) Bot de Telegram

---

## 🚀 Instalación

```bash
git clone https://github.com/jmsantamariar/family-glucose-monitor.git
cd family-glucose-monitor
python -m venv .venv
source .venv/bin/activate        # En Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp config.example.yaml config.yaml
chmod 600 config.yaml
```

---

## ⚙️ Configuración

### LibreLinkUp

Edita `config.yaml`:

```yaml
librelinkup:
  email: "tu-email@ejemplo.com"
  password: "tu-contraseña"
  region: "EU"          # US, EU, EU2, DE, FR, JP, AP, AU, AE, CA, LA, RU
```

O usa variables de entorno (recomendado para Docker):

```bash
export LIBRELINKUP_EMAIL="tu-email@ejemplo.com"
export LIBRELINKUP_PASSWORD="tu-contraseña"
```

### Telegram

1. Habla con [@BotFather](https://t.me/BotFather) en Telegram → `/newbot` → copia el token.
2. Obtén tu `chat_id` con `https://api.telegram.org/bot<TOKEN>/getUpdates`.
3. Edita `config.yaml`:

```yaml
outputs:
  - type: telegram
    enabled: true
    bot_token: "123456:ABC..."
    chat_id: "-100123456789"
```

4. Valida:

```bash
python validate_telegram.py
```

---

## ▶️ Ejecución

### Validar conexión

```bash
python validate_connection.py
```

### Modo cron (una sola lectura)

```bash
python -m src.main
```

Agrega al crontab para ejecutar cada 5 minutos:

```
*/5 * * * * cd /ruta/al/proyecto && .venv/bin/python -m src.main >> /var/log/glucose.log 2>&1
```

### Modo daemon (bucle continuo)

```yaml
# config.yaml
monitoring:
  mode: "daemon"
  interval_seconds: 300
```

```bash
python -m src.main
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

## 🧪 Tests

```bash
pytest tests/ -v
```

---

## 🔒 Seguridad

- `config.yaml` está en `.gitignore` — **nunca** lo subas al repositorio.
- Usa `chmod 600 config.yaml` para restringir el acceso al archivo.
- Para entornos de producción, prefiere variables de entorno o un gestor de secretos.
- Esta librería utiliza una API no oficial de Abbott LibreLinkUp.

---

## 📦 Créditos

- [robberwick/pylibrelinkup](https://github.com/robberwick/pylibrelinkup) — cliente Python para LibreLinkUp
- [rreal/glucose-actions](https://github.com/rreal/glucose-actions) — arquitectura de alertas
- [DiaKEM/libre-link-up-api-client](https://github.com/DiaKEM/libre-link-up-api-client) — referencia de la API
family-glucose-monitor
