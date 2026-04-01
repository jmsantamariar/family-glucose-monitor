# Deployment Guide — Family Glucose Monitor

## Variables de entorno soportadas

| Variable             | Descripción                                                                                      | Predeterminado         |
|----------------------|--------------------------------------------------------------------------------------------------|------------------------|
| `API_KEY`            | Clave de portador para proteger la API externa (`api_server.py`). Si no se define, la API es pública con una advertencia en el log. | Sin definir (no autenticado) |
| `ALERT_HISTORY_DB`   | Ruta al archivo SQLite de historial de alertas.                                                  | `<project_root>/alert_history.db` |
| `CORS_ALLOWED_ORIGINS` | Lista de orígenes CORS separados por comas permitidos en la API externa.                       | `""` (ninguno)         |
| `AUTH_DISABLED`      | Establece `1` para deshabilitar autenticación (solo en entornos de desarrollo).                  | No aplica en producción |
| `APP_ENV` / `ENV`    | Entorno de la aplicación (`production`, `dev`, etc.).                                            | `production`           |

## Proteger la API externa con `API_KEY`

La API externa (`api_server.py`, puerto 8081 por defecto) acepta autenticación opcional
mediante API key. Para habilitarla:

```bash
export API_KEY="tu-clave-secreta-aqui"
```

Luego las peticiones deben incluir el header:

```
Authorization: Bearer tu-clave-secreta-aqui
```

Si `API_KEY` no está definida, la API funciona sin autenticación pero registra una advertencia
en el log al iniciar.

## Lista de verificación para producción

- [ ] Definir `API_KEY` para proteger la API externa.
- [ ] Asegurarse de que `config.yaml` tenga permisos `chmod 600`.
- [ ] Hacer una copia de seguridad del archivo `.secret_key` (sin él, los valores cifrados en `config.yaml` se vuelven ilegibles).
- [ ] Asegurarse de que `AUTH_DISABLED` **no** esté definido en producción.
- [ ] Revisar que la contraseña del panel de control tenga al menos 8 caracteres.
