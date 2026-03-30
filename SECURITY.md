# 🔒 Política de Seguridad / Security Policy

## Manejo de datos de salud (PHI)

Este sistema procesa **datos de salud sensibles** (Protected Health Information / PHI):

- Lecturas de glucosa en sangre en tiempo real
- Nombres de pacientes vinculados a la cuenta LibreLinkUp
- Timestamps de las mediciones
- Tokens de acceso a servicios de mensajería (Telegram, WhatsApp)

El usuario es el único responsable del cumplimiento de las regulaciones de privacidad aplicables (GDPR, HIPAA, LOPD u otras) en su jurisdicción.

---

## Recomendaciones de seguridad

### Credenciales

| Práctica | Recomendación |
|----------|---------------|
| `config.yaml` en producción | ❌ Evitar — usar variables de entorno en su lugar |
| Variables de entorno | ✅ Preferido para tokens y contraseñas |
| Control de permisos | `chmod 600 config.yaml` si se usa el archivo |
| Git | `config.yaml` está en `.gitignore` — **nunca** lo subas al repositorio |

Variables de entorno soportadas:

```bash
LIBRELINKUP_EMAIL="usuario@ejemplo.com"
LIBRELINKUP_PASSWORD="contraseña"
WHATSAPP_ACCESS_TOKEN="token_whatsapp"
```

### Almacenamiento local

- **`state.json`** contiene datos mínimos (nivel y tiempo del último alerta por paciente). Si el sistema opera en un entorno compartido, considera:
  - Almacenarlo en una ruta con permisos restringidos
  - Cifrarlo con herramientas como `gpg` o usar un almacén de secretos

### Bot de Telegram

- No expongas el bot de Telegram públicamente. Configura el bot para que **solo responda a tu `chat_id`**.
- Almacena el `bot_token` como variable de entorno, no en `config.yaml`.
- Rota el token del bot si sospechas que fue comprometido (usa `/revoke` en @BotFather).

### Ejecución con permisos mínimos

- Ejecuta el monitor con un usuario del sistema dedicado (no `root`):
  ```bash
  useradd -r -s /usr/sbin/nologin glucose-monitor
  sudo -u glucose-monitor python -m src.main
  ```
- En Docker, el `Dockerfile` usa un usuario no-root. No ejecutes con `--privileged`.

### Red

- La comunicación con LibreLinkUp, Telegram y WhatsApp se realiza sobre HTTPS.
- En entornos corporativos, asegúrate de que las salidas de red a los endpoints necesarios estén permitidas.

---

## Nota sobre GDPR / HIPAA

Este software **no implementa** controles de cumplimiento GDPR o HIPAA automáticamente. El usuario es responsable de:

- Obtener el consentimiento de las personas cuyos datos de glucosa se monitorizan.
- Definir y documentar las políticas de retención de datos.
- Garantizar que los datos no se transfieran a jurisdicciones no permitidas.
- Cumplir con los derechos de acceso, rectificación y supresión de datos personales.

Consulta con un experto legal antes de desplegar este sistema en un entorno clínico o comercial.

---

## Reporte de vulnerabilidades

Si descubres una vulnerabilidad de seguridad en este proyecto, por favor:

1. **No** la reportes como un Issue público de GitHub.
2. Envía un reporte privado usando [GitHub Security Advisories](https://github.com/jmsantamariar/family-glucose-monitor/security/advisories/new).
3. Incluye:
   - Descripción del problema
   - Pasos para reproducirlo
   - Impacto potencial
   - Sugerencia de solución (opcional)

Los reportes serán atendidos en un plazo de 72 horas hábiles.

---

## Versiones soportadas

| Versión | Soporte de seguridad |
|---------|---------------------|
| `main` (última) | ✅ Activo |
| Versiones anteriores | ❌ Sin soporte |

---

*Para preguntas generales de seguridad, abre un Issue con la etiqueta `security`.*
