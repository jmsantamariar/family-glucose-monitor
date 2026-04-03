# Guía de Despliegue — Family Glucose Monitor

## Variables de entorno soportadas

| Variable | Descripción | Predeterminado |
|----------|-------------|----------------|
| `FGM_MASTER_KEY` | Clave maestra Fernet para descifrar credenciales en `config.yaml` (64 hex chars = 32 bytes). **Obligatoria en producción.** | Sin definir (usa `.secret_key` local) |
| `API_KEY` | Clave Bearer para proteger la API externa (`api_server.py`). **Obligatoria en producción.** Sin esta clave y sin `ALLOW_INSECURE_LOCAL_API=1`, todas las peticiones son rechazadas con 401. | Sin definir (todas las peticiones → 401) |
| `ALERT_HISTORY_DB` | Ruta al archivo SQLite de historial de alertas. | `<project_root>/alert_history.db` |
| `CORS_ALLOWED_ORIGINS` | Lista de orígenes CORS separados por comas permitidos en la API externa. | `""` (ninguno) |
| `AUTH_DISABLED` | `1` para deshabilitar autenticación del dashboard. **Solo funciona si `APP_ENV` es `dev`, `development`, `local` o `test`. Ignorado en producción.** | No aplica en producción |
| `ALLOW_INSECURE_LOCAL_API` | `1` para deshabilitar auth de la API externa. **Solo para desarrollo local. Nunca en producción.** | No definido |
| `APP_ENV` / `ENV` | Entorno de la aplicación (`production`, `dev`, `development`, `local`, `test`). Controla cookies Secure, soporte de `AUTH_DISABLED` y otros comportamientos. | `production` |
| `LIBRELINKUP_EMAIL` | Email de LibreLinkUp (sobreescribe `config.yaml`). | Sin definir |
| `LIBRELINKUP_PASSWORD` | Contraseña de LibreLinkUp (sobreescribe `config.yaml`). | Sin definir |
| `WHATSAPP_ACCESS_TOKEN` | Token de WhatsApp Cloud API (sobreescribe `config.yaml`). | Sin definir |

---

## API externa (`api_server.py`) — Autenticación por defecto

La API externa es **segura por defecto**. Las tres situaciones posibles son:

| Escenario | Comportamiento |
|-----------|---------------|
| `API_KEY` definida | Requiere `Authorization: Bearer <API_KEY>` en cada petición. Sin header válido → 401. |
| `API_KEY` no definida + `ALLOW_INSECURE_LOCAL_API=1` | Acceso sin autenticación. Log de advertencia al arrancar. Solo para dev/local. |
| `API_KEY` no definida + sin `ALLOW_INSECURE_LOCAL_API` | Todas las peticiones rechazadas con 401. |

Para producción, siempre define `API_KEY`:

```bash
export API_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
uvicorn src.api_server:app --host 0.0.0.0 --port 8081
```

Las peticiones deben incluir:

```
Authorization: Bearer <API_KEY>
```

---

## Encriptación de credenciales (`FGM_MASTER_KEY`)

La contraseña de LibreLinkUp se almacena cifrada en `config.yaml` usando Fernet (AES-128-CBC + HMAC-SHA256), derivado con HKDF-SHA256 de la clave maestra.

- **En producción:** inyecta `FGM_MASTER_KEY` como variable de entorno o Docker secret.
- **En desarrollo local:** si `FGM_MASTER_KEY` no está definida, se usa el archivo `.secret_key` en la raíz del proyecto (creado automáticamente si no existe).

> ⚠️ Hacer backup del `.secret_key` o del valor de `FGM_MASTER_KEY`. Sin ellos, los valores cifrados en `config.yaml` son irrecuperables. En ese caso, volver a ejecutar el wizard de setup (`/setup`).

Genera una clave para producción:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## Docker

### Build y ejecución básica

```bash
# Genera las claves y guarda/reemplaza .env:
echo "FGM_MASTER_KEY=$(python -c 'import secrets; print(secrets.token_hex(32))')" > .env
echo "API_KEY=$(python -c 'import secrets; print(secrets.token_hex(32))')" >> .env
chmod 600 .env

# Crea los archivos de estado antes del primer arranque:
touch state.json alert_history.db sessions.db readings_cache.json

docker build -t family-glucose-monitor .
docker run --rm --env-file .env \
  -v $(pwd)/config.yaml:/app/config.yaml:ro \
  -v $(pwd)/state.json:/app/state.json \
  -v $(pwd)/alert_history.db:/app/alert_history.db \
  -v $(pwd)/sessions.db:/app/sessions.db \
  -v $(pwd)/readings_cache.json:/app/readings_cache.json \
  -p 8080:8080 \
  family-glucose-monitor
```

> **Archivos de estado:** Los archivos `state.json`, `alert_history.db`, `sessions.db` y `readings_cache.json` deben existir en el host **antes** del primer arranque. Si no existen, Docker crea un directorio vacío en su lugar y la aplicación falla. Usa `touch` para crearlos vacíos.

> **Setup wizard en Docker:** `config.yaml` se monta como solo lectura (`:ro`). El wizard de setup no puede escribir `config.yaml` desde dentro del contenedor. Genera `config.yaml` fuera del contenedor primero (ejecutando el wizard sin Docker o copiando `config.example.yaml`), y luego monta el archivo resultante.

### Docker Compose (dashboard + API externa)

Crea el directorio de datos y los archivos vacíos antes del primer arranque:

```bash
mkdir -p data
touch data/state.json data/alert_history.db data/sessions.db data/readings_cache.json
```

Genera las claves UNA VEZ y guárdalas en `.env`:

```bash
{
  echo "FGM_MASTER_KEY=$(python -c 'import secrets; print(secrets.token_hex(32))')"
  echo "API_KEY=$(python -c 'import secrets; print(secrets.token_hex(32))')"
} > .env
chmod 600 .env
```

```yaml
services:
  monitor:
    build: .
    environment:
      - FGM_MASTER_KEY=${FGM_MASTER_KEY}
      - API_KEY=${API_KEY}
    volumes:
      - ./config.yaml:/app/config.yaml:ro
      - ./data/state.json:/app/state.json
      - ./data/alert_history.db:/app/alert_history.db
      - ./data/sessions.db:/app/sessions.db
      - ./data/readings_cache.json:/app/readings_cache.json
    ports:
      - "8080:8080"
    restart: unless-stopped

  api:
    build: .
    command: uvicorn src.api_server:app --host 0.0.0.0 --port 8081
    environment:
      - API_KEY=${API_KEY}
      - ALERT_HISTORY_DB=/app/alert_history.db
    volumes:
      - ./data/alert_history.db:/app/alert_history.db:ro
      - ./data/readings_cache.json:/app/readings_cache.json:ro
    ports:
      - "8081:8081"
    depends_on:
      - monitor
    restart: unless-stopped
```

---

## Migraciones de Base de Datos

El esquema de `alert_history.db` se gestiona con Alembic. Las migraciones **no se aplican automáticamente** en runtime; deben ejecutarse manualmente antes del primer arranque o al actualizar a una versión que incluya cambios de schema.

> **Nota:** La imagen Docker de producción instala solo dependencias `main` y no incluye Alembic ni los archivos de migración. Las migraciones deben ejecutarse desde un clone del repositorio con las dependencias de desarrollo instaladas.

```bash
# Desde el directorio raíz del repositorio (requiere dependencias de desarrollo):
poetry run alembic upgrade head
```

Pasa la ruta al archivo de base de datos si no está en la ruta por defecto:

```bash
ALERT_HISTORY_DB=/ruta/a/alert_history.db poetry run alembic upgrade head
```

> **Nota:** `sessions.db` no usa Alembic. Su esquema lo crea `src/auth.py` con DDL raw al arrancar. Si el archivo no existe, se crea automáticamente.

---

## Configurar HTTPS con reverse proxy (recomendado en producción)

No expongas el dashboard ni la API sin HTTPS en producción. Ejemplo con **Caddy**:

```
# Caddyfile
dashboard.tudominio.com {
    reverse_proxy localhost:8080
}

api.tudominio.com {
    reverse_proxy localhost:8081
}
```

Ejemplo con **nginx**:

```nginx
server {
    listen 443 ssl;
    server_name dashboard.tudominio.com;

    ssl_certificate     /etc/letsencrypt/live/tudominio.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/tudominio.com/privkey.pem;

    location / {
        proxy_pass http://localhost:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## Lista de verificación para producción

- [ ] Definir `FGM_MASTER_KEY` como variable de entorno o Docker secret (no en `config.yaml` ni en código).
- [ ] Definir `API_KEY` para proteger la API externa. Sin ella todas las peticiones son rechazadas con 401.
- [ ] Asegurarse de que `config.yaml` tenga permisos `chmod 600`.
- [ ] Hacer copia de seguridad de `FGM_MASTER_KEY` (o del archivo `.secret_key` si se usa en local). Sin ella los valores cifrados en `config.yaml` son irrecuperables.
- [ ] Asegurarse de que `AUTH_DISABLED` **no** esté definido en producción (es ignorado automáticamente si `APP_ENV=production`, pero no definirlo es más seguro).
- [ ] Asegurarse de que `ALLOW_INSECURE_LOCAL_API` **no** esté definido en producción.
- [ ] Montar `alert_history.db`, `sessions.db`, `state.json` y `readings_cache.json` como volúmenes persistentes en Docker.
- [ ] Ejecutar las migraciones de base de datos hasta `head` antes del primer arranque (o tras actualizaciones con cambios de schema en `alert_history.db`), usando el método soportado por el proyecto (por ejemplo, `poetry run alembic upgrade head` en un entorno con dependencias de desarrollo, o el job/imagen específica de migraciones definida en la infraestructura).
- [ ] Configurar un reverse proxy con HTTPS (Caddy, nginx, Traefik) delante del dashboard y la API.
- [ ] Revisar que la contraseña del panel de control tenga al menos 8 caracteres.
- [ ] Verificar que `APP_ENV` sea `production` (o no esté definida) para que las cookies usen `Secure=True`.