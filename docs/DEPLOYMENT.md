# 🚀 Guía de Despliegue

Esta guía cubre las distintas formas de ejecutar Family Glucose Monitor, desde desarrollo local hasta producción con alta disponibilidad.

---

## Tabla de contenidos

1. [Modos de ejecución](#modos-de-ejecución)
2. [Componentes del sistema](#componentes-del-sistema)
3. [Desarrollo local](#desarrollo-local)
4. [Producción con systemd](#producción-con-systemd)
5. [Producción con Docker](#producción-con-docker)
6. [Reverse proxy y HTTPS](#reverse-proxy-y-https)
7. [Variables de entorno y secretos](#variables-de-entorno-y-secretos)
8. [Permisos de archivos](#permisos-de-archivos)
9. [Caveats operativos](#caveats-operativos)

---

## Modos de ejecución

El modo se configura en config.yaml bajo monitoring.mode:

| Modo | Qué hace | Polling a LibreLinkUp | Ciclo de alertas/salidas | Dashboard web | API externa |
|-------------|-----------------------------------------------------------|-----------------------|--------------------------|---------------|-------------|
| cron | Una sola lectura y salida | ✅ durante la ejecución | ✅ durante la ejecución | ❌ | ❌ |
| daemon | Bucle continuo en foreground | ✅ cada N segundos | ✅ continuo | ❌ | ❌ |
| dashboard | Panel web; polling a LibreLinkUp en background, sin alertas/salidas | ✅ en segundo plano (vía api.py) | ❌ | ✅ | ❌ |
| full | Dashboard + ciclo de alertas/salidas | ✅ en segundo plano | ✅ en segundo plano | ✅ | ❌ |

La API externa (src/api_server.py) se ejecuta siempre por separado, independientemente del modo anterior. Ver Componentes del sistema.

### Cron (recomendado para uso simple)

Ejecuta python -m src.main una sola vez. El sistema operativo se encarga de la periodicidad.

```yaml
# config.yaml
monitoring:
  mode: "cron"
  interval_seconds: 300   # ignorado en modo cron
```

```crontab
# crontab -e
*/5 * * * * cd /opt/family-glucose-monitor && .venv/bin/python -m src.main >> /var/log/glucose.log 2>&1
```

Ventajas: sencillo, sin proceso persistente, reinicio automático ante fallos.  
Desventaja: no disponible como servicio web (no hay dashboard en este modo).

### Daemon (proceso continuo)

```yaml
monitoring:
  mode: "daemon"
  interval_seconds: 300
```

```bash
python -m src.main
```

Se queda en foreground. Usa systemd o supervisor para gestionarlo como servicio.

### Dashboard (panel web con polling, sin ciclo de alertas)

```yaml
monitoring:
  mode: "dashboard"

dashboard:
  host: "127.0.0.1"   # usar 127.0.0.1 detrás de reverse proxy
  port: 8080
```

```bash
python -m src.main
```

Solo lanza el servidor FastAPI (src/api.py) en host:port. El dashboard hace polling a LibreLinkUp en segundo plano para mostrar lecturas en tiempo real, pero no ejecuta el ciclo de alertas/salidas.

### Full (monitoreo + dashboard)

```yaml
monitoring:
  mode: "full"
  interval_seconds: 300

dashboard:
  host: "127.0.0.1"
  port: 8080
```

```bash
python -m src.main
```

Arranca el dashboard en un hilo de segundo plano y corre el bucle de monitoreo en primer plano. Es el modo más completo para un único proceso.

---

## Componentes del sistema

El proyecto tiene dos servidores FastAPI independientes con propósitos distintos:

### src/api.py — Dashboard interno

- Sirve la UI web (HTML/JS) y sus APIs de soporte
- Requiere autenticación con cookie de sesión
- Hace polling activo a LibreLinkUp en un hilo interno
- Expone endpoints para pacientes, alertas, estado de salud y configuración inicial
- No tiene CORS habilitado — solo para consumo desde el mismo dominio
- Se lanza con monitoring.mode: dashboard o full vía python -m src.main

### src/api_server.py — API externa (solo lectura)

- API REST ligera para consumo externo (widgets, watchfaces, apps móviles)
- No requiere autenticación — expone datos de solo lectura
- Lee del archivo readings_cache.json que src/main.py actualiza en cada ciclo
- CORS está **cerrado por defecto**; permite orígenes explícitos con la variable de entorno `CORS_ALLOWED_ORIGINS` (lista separada por comas)
- Se lanza manualmente con uvicorn:

```bash
uvicorn src.api_server:app --host 127.0.0.1 --port 8081
```

### Endpoints de cada componente

| Componente | Endpoint | Descripción |
|-----------------|--------------------------|---------------------------------------------|
| src/api.py | GET / | Dashboard HTML |
| src/api.py | GET /api/patients | Lecturas en memoria (autenticado) |
| src/api.py | GET /api/patients/{id} | Lectura de un paciente (autenticado) |
| src/api.py | GET /api/health | Estado del dashboard |
| src/api.py | GET /api/alerts | Historial de alertas (autenticado) |
| src/api.py | POST /api/login | Autenticación |
| src/api.py | POST /api/setup | Configuración inicial |
| src/api_server.py | GET /api/readings | Lecturas cacheadas (sin auth) |
| src/api_server.py | GET /api/readings/{id} | Lectura de un paciente (sin auth) |
| src/api_server.py | GET /api/health | Estado de la API externa |
| src/api_server.py | GET /api/alerts | Historial de alertas (sin auth) |

> **Nota:** src/api.py y src/api_server.py exponen rutas con el mismo prefijo `/api/` pero con contratos distintos. No se deben publicar en el mismo dominio/puerto sin un proxy que las diferencie.

---

## Desarrollo local

```bash
# 1. Clonar e instalar
git clone https://github.com/jmsantamariar/family-glucose-monitor.git
cd family-glucose-monitor
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Configurar
cp config.example.yaml config.yaml
chmod 600 config.yaml
# Editar config.yaml con credenciales

# 3. Validar conexión
python validate_connection.py

# 4. Ejecutar (modo cron, una lectura)
python -m src.main

# 5. Opcional: dashboard en otro terminal
# Cambiar monitoring.mode: "dashboard" en config.yaml
python -m src.main
# → Dashboard en http://localhost:8080
```

En desarrollo, usar host: "0.0.0.0" es aceptable, pero en producción usar 127.0.0.1 y dejar que el reverse proxy exponga el servicio.

---

## Producción con systemd

### Servicio del monitor (modo full)

Crear /etc/systemd/system/glucose-monitor.service:

```ini
[Unit]
Description=Family Glucose Monitor
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=glucose
WorkingDirectory=/opt/family-glucose-monitor
ExecStart=/opt/family-glucose-monitor/.venv/bin/python -m src.main
Restart=always
RestartSec=30

# Usar variables de entorno para secretos en lugar de config.yaml
EnvironmentFile=/etc/glucose-monitor/env
Environment=PYTHONUNBUFFERED=1

StandardOutput=journal
StandardError=journal
SyslogIdentifier=glucose-monitor

# Límites de seguridad
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/opt/family-glucose-monitor

[Install]
WantedBy=multi-user.target
```

### Servicio de la API externa (opcional)

Crear /etc/systemd/system/glucose-api.service:

```ini
[Unit]
Description=Family Glucose Monitor - External API
After=network.target glucose-monitor.service

[Service]
Type=simple
User=glucose
WorkingDirectory=/opt/family-glucose-monitor
ExecStart=/opt/family-glucose-monitor/.venv/bin/uvicorn src.api_server:app --host 127.0.0.1 --port 8081 --no-access-log
Restart=always
RestartSec=10

EnvironmentFile=/etc/glucose-monitor/env
Environment=PYTHONUNBUFFERED=1

StandardOutput=journal
StandardError=journal
SyslogIdentifier=glucose-api

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/opt/family-glucose-monitor

[Install]
WantedBy=multi-user.target
```

```bash
# Habilitar e iniciar
sudo systemctl daemon-reload
sudo systemctl enable glucose-monitor glucose-api
sudo systemctl start glucose-monitor glucose-api

# Ver logs
sudo journalctl -u glucose-monitor -f
sudo journalctl -u glucose-api -f
```

---

## Producción con Docker

### Monitor + Dashboard (modo full)

```bash
docker run -d \
  --name glucose-monitor \
  --restart unless-stopped \
  -v /etc/glucose/config.yaml:/app/config.yaml:ro \
  -v /var/lib/glucose/state.json:/app/state.json \
  -v /var/lib/glucose/alert_history.db:/app/alert_history.db \
  -v /var/lib/glucose/readings_cache.json:/app/readings_cache.json \
  -p 127.0.0.1:8080:8080 \
  -e LIBRELINKUP_EMAIL=tu@email.com \
  -e LIBRELINKUP_PASSWORD=tu_contraseña \
  family-glucose-monitor
```

> Usar `-p 127.0.0.1:8080:8080` para exponer solo localmente; el reverse proxy publica HTTPS.

### API externa

```bash
docker run -d \
  --name glucose-api \
  --restart unless-stopped \
  -v /var/lib/glucose/readings_cache.json:/app/readings_cache.json:ro \
  -v /var/lib/glucose/alert_history.db:/app/alert_history.db:ro \
  -p 127.0.0.1:8081:8081 \
  family-glucose-monitor \
  uvicorn src.api_server:app --host 0.0.0.0 --port 8081
```

### Docker Compose

```yaml
# docker-compose.yml
version: "3.9"

services:
  monitor:
    build: .
    restart: unless-stopped
    volumes:
      - ./config.yaml:/app/config.yaml:ro
      - /var/lib/glucose/state.json:/app/state.json
      - /var/lib/glucose/alert_history.db:/app/alert_history.db
      - /var/lib/glucose/readings_cache.json:/app/readings_cache.json
    ports:
      - "127.0.0.1:8080:8080"
    env_file: .env
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/api/health"]
      interval: 60s
      timeout: 10s
      retries: 3

  api:
    build: .
    restart: unless-stopped
    command: uvicorn src.api_server:app --host 0.0.0.0 --port 8081
    volumes:
      - /var/lib/glucose/readings_cache.json:/app/readings_cache.json:ro
      - /var/lib/glucose/alert_history.db:/app/alert_history.db:ro
    ports:
      - "127.0.0.1:8081:8081"
    env_file: .env
    depends_on:
      - monitor
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8081/api/health"]
      interval: 60s
      timeout: 10s
      retries: 3
```

> Cada servicio monta solo los archivos de datos que necesita; no montes `/app` completo para no ocultar el código de la imagen.

---

## Reverse proxy y HTTPS

**Nunca** expongas el dashboard o la API directamente a Internet sin HTTPS.

(Sección Nginx igual que antes.)

### CORS en producción

`src/api_server.py` inicia con CORS **cerrado**. Para habilitar orígenes permitidos:

```env
CORS_ALLOWED_ORIGINS=https://tu-app-cliente.com,https://otro-cliente.com
```

Si la API solo la consume tu propio dashboard en el mismo dominio, puedes dejarlo vacío.

---

## Variables de entorno y secretos

| Variable | Descripción | Equivalente en config |
|----------|-------------|-----------------------|
| LIBRELINKUP_EMAIL | Email de LibreLinkUp | librelinkup.email |
| LIBRELINKUP_PASSWORD | Contraseña de LibreLinkUp | librelinkup.password |
| WHATSAPP_ACCESS_TOKEN | Token WhatsApp Cloud API | outputs[whatsapp].access_token |
| ALERT_HISTORY_DB | Ruta al SQLite de alertas | alert_history_db |
| CORS_ALLOWED_ORIGINS | Lista de orígenes CORS permitidos (coma) | — |
| AUTH_DISABLED | **Solo dev/test**: si 1, desactiva login; ignorado en producción | — |

Nunca pongas secretos en `config.yaml` en producción; usa variables de entorno o gestor de secretos.

---

## Permisos de archivos

(Mismo contenido que antes.)

---

## Caveats operativos

Añadir nota: En Windows el lock no funciona (usa fcntl); considerar `filelock`.