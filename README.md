# Family Glucose Monitor

Monitor de glucosa familiar con soporte multi-paciente. Lee los datos de glucosa de todos los pacientes vinculados en LibreLinkUp y envía alertas cuando los niveles están fuera del rango configurado.

## Características

- **Multi-paciente**: Monitorea a todos los pacientes vinculados en tu cuenta LibreLinkUp simultáneamente
- **Alertas configurables**: Umbrales de glucosa baja y alta personalizables
- **Cooldown por paciente**: Evita spam de alertas con un período de enfriamiento independiente por paciente
- **Múltiples salidas**: Telegram, Webhook HTTP, y WhatsApp Cloud API
- **Estado persistente**: Recuerda el estado entre ejecuciones (modo cron)
- **Modo cron y daemon**: Flexible para cualquier configuración de despliegue

## Requisitos

- Python 3.12+
- Cuenta en [LibreLinkUp](https://librelinkup.com)
- Al menos un sensor FreeStyle Libre vinculado

## Instalación

```bash
git clone https://github.com/jmsantamariar/family-glucose-monitor.git
cd family-glucose-monitor
pip install -r requirements.txt
cp config.example.yaml config.yaml
chmod 600 config.yaml
# Editar config.yaml con tus credenciales
```

## Configuración

Edita `config.yaml` con tus valores:

```yaml
librelinkup:
  email: "tu-email@ejemplo.com"
  password: "tu-contraseña"
  region: "EU"  # o "US", "DE", etc.

alerts:
  low_threshold: 70    # mg/dL — alerta de glucosa baja
  high_threshold: 180  # mg/dL — alerta de glucosa alta
  cooldown_minutes: 20 # minutos entre alertas repetidas del mismo nivel
  max_reading_age_minutes: 15  # ignorar lecturas más antiguas que esto

outputs:
  - type: telegram
    enabled: true
    bot_token: "tu-bot-token"
    chat_id: "tu-chat-id"
```

Las credenciales también pueden pasarse como variables de entorno:
- `LIBRELINKUP_EMAIL`
- `LIBRELINKUP_PASSWORD`
- `WHATSAPP_ACCESS_TOKEN`

## Uso

### Modo cron (recomendado)

```bash
# Ejecutar una vez
python -m src.main

# Agregar a crontab (cada 5 minutos)
*/5 * * * * /usr/bin/python3 -m src.main
```

### Modo daemon

```yaml
# En config.yaml
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
docker run -v $(pwd)/config.yaml:/app/config.yaml family-glucose-monitor
```

## Validación de conexión

```bash
# Verificar conexión con LibreLinkUp
python validate_connection.py

# Verificar bot de Telegram
python validate_telegram.py
```

## Diseño multi-paciente

La diferencia clave respecto a otros monitores es que este sistema lee **todos** los pacientes vinculados:

```python
patients = client.get_patients()  # lista completa
for patient in patients:
    latest = client.latest(patient)  # lectura más reciente
    # Se evalúa y alerta independientemente para cada paciente
```

El estado de alertas se mantiene **por paciente** (keyed by `patient_id`) para que el cooldown sea independiente para cada persona de la familia.

## Salidas disponibles

### Telegram
- Envía mensajes de texto con HTML
- Configuración: `bot_token` y `chat_id`
- Obtén un bot con [@BotFather](https://t.me/botfather)

### Webhook HTTP
- POST JSON a cualquier URL
- Compatible con ntfy, Gotify, Home Assistant, etc.

### WhatsApp Cloud API
- Usa la API oficial de Meta
- Requiere template aprobado y Business Account

## Tests

```bash
pytest tests/
```

## Licencia

MIT License — ver [LICENSE](LICENSE)
