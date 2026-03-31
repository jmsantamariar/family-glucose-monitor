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

El modo se configura en `config.yaml` bajo `monitoring.mode`:

| Modo | Qué hace | Polling a LibreLinkUp | Ciclo de alertas/salidas | Dashboard web | API externa |
|------|----------|-----------------------|--------------------------|---------------|-------------|
| `cron` | Una sola lectura y salida | ✅ durante la ejecución | ✅ durante la ejecución | ❌ | ❌ |
| `daemon` | Bucle continuo en foreground | ✅ cada N segundos | ✅ continuo | ❌ | ❌ |
| `dashboard` | Panel web; polling a LibreLinkUp en background, sin alertas/salidas | ✅ en segundo plano (vía `api.py`) | ❌ | ✅ | ❌ |
| `full` | Dashboard + ciclo de alertas/salidas | ✅ en segundo plano | ✅ en segundo plano | ✅ | ❌ |

La API externa (`src/api_server.py`) se ejecuta **siempre por separado**, independientemente del modo anterior. Ver [Componentes del sistema](#componentes-del-sistema).

### Cron (recomendado para uso simple)

Ejecuta `python -m src.main` una sola vez. El sistema operativo se encarga de la periodicidad.

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

**Ventajas:** sencillo, sin proceso persistente, reinicio automático ante fallos.  
**Desventaja:** no disponible como servicio web (no hay dashboard en este modo).

### Daemon (proceso continuo)

```yaml
monitoring:
  mode: "daemon"
  interval_seconds: 300
```

```bash
python -m src.main
```

Se queda en foreground. Usa `systemd` o `supervisor` para gestionarlo como servicio.

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

Solo lanza el servidor FastAPI (`src/api.py`) en `host:port`. El dashboard hace polling a LibreLinkUp en segundo plano para mostrar lecturas en tiempo real, pero **no ejecuta el ciclo de alertas/salidas ni escribe `readings_cache.json`**. Útil como panel de solo visualización o cuando otro proceso externo ya corre el ciclo de alertas.

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

El proyecto tiene **dos servidores FastAPI independientes** con propósitos distintos:

### `src/api.py` — Dashboard interno

- Sirve la UI web (HTML/JS) y sus APIs de soporte
- Requiere autenticación con cookie de sesión
- Hace polling activo a LibreLinkUp en un hilo interno
- Expone endpoints para pacientes, alertas, estado de salud y configuración inicial
- **No tiene CORS habilitado** — solo para consumo desde el mismo dominio
- Se lanza con `monitoring.mode: dashboard` o `full` vía `python -m src.main`

### `src/api_server.py` — API externa (solo lectura)

- API REST ligera para consumo externo (widgets, watchfaces, apps móviles)
- **No requiere autenticación** — expone datos de solo lectura
- Lee del archivo `readings_cache.json` que `src/main.py` actualiza en cada ciclo
- Tiene CORS configurado (actualmente `allow_origins=["*"]` — ver recomendaciones en [CORS en producción](#cors-en-producción))
- Se lanza manualmente con `uvicorn`:

```bash
uvicorn src.api_server:app --host 127.0.0.1 --port 8081
```

### Endpoints de cada componente

| Componente | Endpoint | Descripción |
|------------|----------|-------------|
| `src/api.py` | `GET /` | Dashboard HTML |
| `src/api.py` | `GET /api/patients` | Lecturas en memoria (autenticado) |
| `src/api.py` | `GET /api/patients/{id}` | Lectura de un paciente (autenticado) |
| `src/api.py` | `GET /api/health` | Estado del dashboard |
| `src/api.py` | `GET /api/alerts` | Historial de alertas (autenticado) |
| `src/api.py` | `POST /api/login` | Autenticación |
| `src/api.py` | `POST /api/setup` | Configuración inicial |
| `src/api_server.py` | `GET /api/readings` | Lecturas cacheadas (sin auth) |
| `src/api_server.py` | `GET /api/readings/{id}` | Lectura de un paciente (sin auth) |
| `src/api_server.py` | `GET /api/health` | Estado de la API externa |
| `src/api_server.py` | `GET /api/alerts` | Historial de alertas (sin auth) |

> **Nota:** `src/api.py` y `src/api_server.py` exponen rutas con el mismo prefijo `/api/` pero con contratos distintos. No se deben publicar en el mismo dominio/puerto sin un proxy que las diferencie.

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

**En desarrollo, usar `host: "0.0.0.0"` es aceptable**, pero en producción usar `127.0.0.1` y dejar que el reverse proxy exponga el servicio.

---

## Producción con systemd

### Servicio del monitor (modo full)

Crear `/etc/systemd/system/glucose-monitor.service`:

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

Crear `/etc/systemd/system/glucose-api.service`:

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

> Usar `-p 127.0.0.1:8080:8080` (no `0.0.0.0:8080:8080`) para que el puerto solo sea accesible localmente. El reverse proxy se encarga de exponer al exterior.

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
```

> **Nota:** cada servicio monta solo los archivos de datos que necesita directamente sobre `/app`, sin ocultar el código de la imagen. Crea previamente los archivos en el host: `touch /var/lib/glucose/state.json /var/lib/glucose/alert_history.db /var/lib/glucose/readings_cache.json`.

---

## Reverse proxy y HTTPS

**En producción, nunca exponer el dashboard o la API directamente a Internet sin HTTPS.**

### Nginx

```nginx
# /etc/nginx/sites-available/glucose

# Dashboard (requiere autenticación propia)
server {
    listen 443 ssl http2;
    server_name glucose.tudominio.com;

    ssl_certificate     /etc/letsencrypt/live/glucose.tudominio.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/glucose.tudominio.com/privkey.pem;

    # Seguridad adicional
    add_header Strict-Transport-Security "max-age=63072000" always;
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

# API externa (para widgets/apps)
server {
    listen 443 ssl http2;
    server_name glucose-api.tudominio.com;

    ssl_certificate     /etc/letsencrypt/live/glucose-api.tudominio.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/glucose-api.tudominio.com/privkey.pem;

    # Restringir orígenes CORS desde el proxy si es posible
    # (complementa la config de allow_origins en api_server.py)

    location /api/ {
        proxy_pass http://127.0.0.1:8081;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}

# Redirección HTTP → HTTPS
server {
    listen 80;
    server_name glucose.tudominio.com glucose-api.tudominio.com;
    return 301 https://$host$request_uri;
}
```

### Certificados con Let's Encrypt

> **Prerrequisito:** los registros DNS (A o AAAA) de cada dominio deben apuntar a la IP del servidor **antes** de ejecutar certbot. Si los dos dominios apuntan a servidores distintos, emite el certificado de cada uno por separado.

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d glucose.tudominio.com -d glucose-api.tudominio.com
```

### CORS en producción

`src/api_server.py` actualmente configura `allow_origins=["*"]`, lo que permite peticiones desde cualquier dominio. Para producción, edita el middleware en `src/api_server.py` para restringir el origen al dominio de tu aplicación cliente:

```python
# src/api_server.py — ajuste para producción
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://tu-app-cliente.com"],   # lista explícita de orígenes permitidos
    allow_methods=["GET"],
    allow_headers=["*"],
)
```

Si la API solo la consume tu propio dashboard (mismo dominio), puedes eliminar el middleware CORS por completo y confiar en que el proxy gestiona el enrutamiento.

---

## Variables de entorno y secretos

El sistema soporta sobrescribir valores de `config.yaml` con variables de entorno. Es la forma recomendada de manejar secretos en producción.

| Variable de entorno | Descripción | Archivo config equivalente |
|---------------------|-------------|---------------------------|
| `LIBRELINKUP_EMAIL` | Email de LibreLinkUp | `librelinkup.email` |
| `LIBRELINKUP_PASSWORD` | Contraseña de LibreLinkUp | `librelinkup.password` |
| `WHATSAPP_ACCESS_TOKEN` | Token de acceso WhatsApp Cloud API | `outputs[whatsapp].access_token` |
| `ALERT_HISTORY_DB` | Ruta al archivo de historial SQLite | `alert_history_db` |
| `AUTH_DISABLED` | Si es `1`, desactiva la autenticación del dashboard (solo para dev) | — |

Ejemplo de archivo `/etc/glucose-monitor/env`:

```env
LIBRELINKUP_EMAIL=tu@email.com
LIBRELINKUP_PASSWORD=contraseña_segura
WHATSAPP_ACCESS_TOKEN=token_whatsapp
ALERT_HISTORY_DB=/var/lib/glucose/alert_history.db
```

> **Nunca** pongas estos valores directamente en `config.yaml` en producción si el archivo puede ser accedido por más personas o estar en un repositorio. Usa variables de entorno o un gestor de secretos.

---

## Permisos de archivos

```bash
# config.yaml solo debe ser legible por el usuario del servicio
chmod 600 config.yaml
chown glucose:glucose config.yaml

# Directorio de datos
mkdir -p /var/lib/glucose
chown glucose:glucose /var/lib/glucose
chmod 750 /var/lib/glucose

# Archivos de datos
touch /var/lib/glucose/state.json
touch /var/lib/glucose/alert_history.db
touch /var/lib/glucose/readings_cache.json
chown glucose:glucose /var/lib/glucose/*
chmod 640 /var/lib/glucose/*
```

Resumen de archivos sensibles:

| Archivo | Permisos recomendados | Contenido |
|---------|-----------------------|-----------|
| `config.yaml` | `600` | Credenciales, umbrales, configuración |
| `state.json` | `640` | Estado de alertas por paciente |
| `alert_history.db` | `640` | Historial de alertas en SQLite |
| `readings_cache.json` | `640` | Últimas lecturas cacheadas |

---

## Caveats operativos

### Lock de instancia única (modos con bucle de monitoreo: `cron`, `daemon`, `full`)

En modos `cron`, `daemon` y `full`, el sistema adquiere un lock exclusivo en `/tmp/family-glucose-monitor.lock` (configurable con `lock_file` en `config.yaml`). Si una ejecución tarda más que el intervalo del cron, la siguiente intentará adquirir el lock y saldrá limpiamente para evitar duplicación de alertas y condiciones de carrera en `state.json`.

En Windows este lock no funciona (usa `fcntl` de Unix). Si tu entorno es Windows, podrías lanzar instancias duplicadas; considera usar `filelock` como dependencia cross-platform.

### Datos en memoria del Dashboard (`src/api.py`)

El dashboard mantiene las últimas lecturas en memoria. Al reiniciar el proceso, la caché se vacía y tardará un intervalo en repoblarse. Durante ese tiempo, el dashboard mostrará "sin datos".

### Cache compartida entre monitor y API externa

El monitor escribe `readings_cache.json` de forma atómica (archivo temporal + `os.replace`). La API externa (`src/api_server.py`) lee siempre el archivo en `PROJECT_ROOT/readings_cache.json` (ruta fija). Si la API externa se inicia antes de que el monitor haya hecho su primera escritura, devolverá lecturas vacías hasta que el monitor complete su primer ciclo.

> **Limitación:** aunque `config.yaml` admite `api.cache_file` para personalizar la ruta del archivo cache que escribe `src/main.py`, `src/api_server.py` siempre lee desde su `PROJECT_ROOT/readings_cache.json` fijo. Para que ambos compartan el mismo archivo, mantén el nombre por defecto (`readings_cache.json`) o monta el archivo en esa ruta dentro del contenedor.

### Sesiones del Dashboard en memoria

Las sesiones de autenticación del dashboard (`src/api.py`) se almacenan en memoria. Al reiniciar el proceso, todas las sesiones activas se invalidan y los usuarios necesitarán hacer login de nuevo. TTL de sesión: 24 horas.

### Dependencia de LibreLinkUp

La API de LibreLinkUp no es pública ni está documentada oficialmente. Si Abbott cambia el protocolo, las lecturas dejarán de funcionar hasta que se actualice la librería `pylibrelinkup`. Configura alertas de monitoreo en `alert_history.db` o revisar logs regularmente en producción.

### Lecturas obsoletas (stale)

Si LibreLinkUp devuelve una lectura con más de `max_reading_age_minutes` minutos de antigüedad, la alerta es suprimida. El dato sí queda en cache. Revisar los logs si las alertas esperadas no llegan.
