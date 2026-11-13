# SERVAMAR - activar PostgreSQL para notificaciones (PRUEBA DE 30 DÍAS)

## Estado y alcance
La base gratuita `servamar-demo-push-30dias` se creó el 13/11/2026.
Vence el **13/12/2026**. No incluye copias de seguridad. No introducir datos reales.

Esta base contiene SOLAMENTE:
- Suscripciones Web Push de Windows/Android (endpoints y claves públicas del dispositivo).
- Clave privada VAPID del servicio (debe tratarse como secreto).
- Estado de avisos diarios y entregas por dispositivo.

Los expedientes de muestra siguen en la base SQLite temporal de Render.

## Vincular base al servicio
1. En Render abre la base `servamar-demo-push-30dias`.
2. Copia el valor **Internal Database URL**. Nunca lo pongas en GitHub ni el chat.
3. En el servicio `servamar-demo-gratis-2y03` -> Environment -> Add Environment Variable:
   `SERVAMAR_PUSH_DATABASE_URL` = Internal Database URL.
4. Elige **Save, deploy** (o guarda y luego Manual Deploy -> Deploy latest commit).
5. Confirma en los logs que sigue Live. En la app, activa de nuevo push
   UNA VEZ en Windows y Android para guardar la suscripción en PostgreSQL.
6. Prueba con la acción manual `Enviar prueba en 12 segundos`, y luego
   ejecuta GitHub Actions `SERVAMAR - revisión diaria de avisos DEMO`.
7. Realiza un nuevo despliegue y verifica que no debas reactivar push.

## Importante
- PostgreSQL gratuito expira a los 30 días (13/12/2026). Al vencer queda
  inaccesible salvo actualización de plan y Render puede eliminar la base
  al pasar el período de gracia.
- No cambiar el plan ni activar recursos de pago sin consentimiento.
- GitHub Actions no garantiza entregas exactamente a las 08:00 ni que
  un proveedor Web Push presente un aviso inmediatamente.
- PostgreSQL persiste entre reinicios mientras la base existe; NO debe
  confundirse con archivado permanente ni con un sistema de alta disponibilidad.
- Si la variable de conexión es incorrecta el servicio puede no iniciar:
  restaura el valor correcto en Environment.
