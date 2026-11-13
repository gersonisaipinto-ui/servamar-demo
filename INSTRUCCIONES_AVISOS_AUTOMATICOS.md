# SERVAMAR - comprobación diaria de Web Push (solo DEMO)

Este flujo revisa los vencimientos ficticios cada día alrededor de las 08:00 de Guatemala.
No transmite datos de embarcaciones, capitán, permisos, correos de clientes ni ejecuta
envíos de correos. No activa automatizaciones de la instalación local.

## Activación de GitHub Actions

En el repositorio: Settings > Secrets and variables > Actions > New repository secret.
Crea dos secretos, usando exactamente los valores ya configurados en Render:

- SERVAMAR_DEMO_USERNAME (valor de APP_USERNAME del servicio de prueba).
- SERVAMAR_DEMO_PASSWORD (valor de APP_PASSWORD del servicio de prueba).

No ingreses estas claves en archivos del repositorio ni en el chat.
En Actions > SERVAMAR - revisión diaria de avisos DEMO > Run workflow puedes
probar manualmente. Un resultado `alerts: 0` solo indica que no corresponde
enviar recordatorios para la fecha calculada.

## Limitaciones

Render gratuito puede suspenderse o reiniciarse. El almacenamiento temporal
contiene las suscripciones, la clave VAPID y el registro de avisos diarios:
al reiniciarse pueden perderse; los dispositivos tendrán que pulsar
«Activar avisos» nuevamente. Por lo tanto, este flujo NO garantiza entregas
permanentes ni debe utilizarse con expedientes reales.

GitHub Actions puede demorar o incluso omitir ejecuciones programadas.
La ejecución diaria está en la zona horaria Guatemala (UTC-6 fijo);
el cron 14:00 UTC NO garantiza ejecución exacta a las 08:00.

Para producción se requiere almacenamiento persistente de suscripciones,
VAPID estable protegido, un almacén transaccional de deduplicación,
monitorización de entrega y un programador fiable.
