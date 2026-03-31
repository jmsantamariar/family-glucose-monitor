# 🔐 Privacidad de Datos / Data Privacy

## Qué datos se procesan

Este sistema procesa los siguientes datos personales y de salud:

| Dato | Fuente | Propósito |
|------|--------|-----------|
| Lecturas de glucosa (mg/dL) | LibreLinkUp API | Evaluar umbrales y generar alertas |
| Nombre del paciente | LibreLinkUp API | Identificar al paciente en las alertas |
| `patient_id` (UUID) | LibreLinkUp API | Clave para el estado de alertas por paciente |
| Timestamps de mediciones | LibreLinkUp API | Detectar lecturas obsoletas (stale) |
| Flecha de tendencia | LibreLinkUp API | Contexto adicional en el mensaje de alerta |

---

## Dónde se almacenan los datos

### En el sistema local

- **`state.json`** — almacena el `patient_id`, el nivel de la última alerta (`low`/`high`) y el timestamp de cuándo se envió. Se usa para controlar el cooldown y evitar alertas repetitivas.
- **`config.yaml`** — credenciales de LibreLinkUp y tokens de servicios de mensajería. Debe tener permisos `600`.

### En la nube / servicios externos

Este sistema **NO almacena datos en la nube**. Sin embargo, **transmite datos** a:

| Servicio | Datos transmitidos | Cuándo |
|----------|-------------------|--------|
| LibreLinkUp API (Abbott) | Credenciales de login | En cada ciclo de lectura |
| Telegram Bot API | Mensaje de alerta (incluye nombre y valor de glucosa) | Cuando se detecta alerta |
| WhatsApp Cloud API (Meta) | Template de alerta con parámetros | Cuando se detecta alerta |
| Webhook externo | Payload JSON con glucosa y nivel | Cuando se detecta alerta |

---

## Qué NO hace este sistema

- ❌ No almacena histórico de lecturas de glucosa.
- ❌ No comparte datos con terceros más allá de los servicios configurados.
- ❌ No tiene acceso a datos de otros usuarios de LibreLinkUp.
- ❌ No utiliza cookies, tracking ni analítica.

---

## Responsabilidad del usuario

El usuario es el único responsable de:

1. **Consentimiento**: Obtener el consentimiento informado de las personas cuyos datos de glucosa se monitorizan.
2. **Bases legales**: Establecer la base legal para el tratamiento de datos según la legislación aplicable (GDPR Art. 6/9, HIPAA, etc.).
3. **Cumplimiento regulatorio**: Cumplir con las obligaciones de protección de datos en su jurisdicción.
4. **Seguridad del entorno**: Proteger el servidor o dispositivo donde se ejecuta el sistema.
5. **Acceso al `state.json`**: Restringir el acceso al archivo de estado que contiene datos de salud.

---

## Recomendaciones de retención de datos

| Dato | Recomendación |
|------|---------------|
| `state.json` | Purgar manualmente cuando ya no sea necesario el monitoreo |
| Logs del sistema | Retener máximo 30 días; no incluir valores de glucosa en logs de nivel INFO+ |
| `config.yaml` | Eliminar credenciales cuando se dejen de usar; no respaldar en la nube sin cifrado |
| Mensajes de Telegram/WhatsApp | Configurar auto-borrado en el chat (Telegram: ajustes del chat → eliminar mensajes automáticamente) |

---

## Transferencias internacionales de datos

- **LibreLinkUp**: Abbott procesa datos en sus servidores. Consulta la [política de privacidad de Abbott](https://www.librelinkup.com/privacy-policy).
- **Telegram**: Telegram puede almacenar mensajes en servidores distribuidos. Consulta la [política de privacidad de Telegram](https://telegram.org/privacy).
- **WhatsApp**: Meta procesa los mensajes en sus infraestructuras. Consulta la [política de privacidad de Meta](https://www.whatsapp.com/legal/privacy-policy).

---

*Para preguntas sobre privacidad, consulta también [SECURITY.md](../SECURITY.md) y [DISCLAIMER.md](../DISCLAIMER.md).*
