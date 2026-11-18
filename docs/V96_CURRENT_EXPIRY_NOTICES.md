# V96: avisos según el vencimiento actual

La aclaración del usuario sustituye la suspensión permanente de V95. En ingreso,
ampliación y depósito, el calendario corresponde siempre al vencimiento actual:
**30 días, 15 días y 1 día antes**. Se mantiene la confirmación previa de 30 días
exactos, no un mes calendario. Los cálculos de permisos de V94 no cambian.

Al ampliar, registrar depósito, cambiar el ingreso o vencimiento manual, editar
o eliminar movimientos, se recalcula primero el permiso. En la misma transacción
se cancelan los planes anteriores y los eventos automáticos pendientes/fallidos
de vencimientos obsoletos; se generan los planes de la fecha actual. No se duplican
por guardar repetidamente. Si se elimina un movimiento y vuelve una fecha anterior,
su plan vuelve a ser el actual. Un aviso ya enviado para esa fecha/canal no se
programa de nuevo. Los enviados y los eventos manuales se conservan.

Ejemplo: ingreso 04/11/2026 → vence 02/02/2027 → avisos 03/01, 18/01 y 01/02/2027.
Ampliación → vence 02/11/2027 → avisos 03/10, 18/10 y 01/11/2027.
Depósito el 12/11/2026 → vence 12/11/2027 → avisos 13/10, 28/10 y 11/11/2027.
Cada paso cancela los pendientes de la fecha anterior. El depósito se cuenta
desde su fecha de ingreso; no desde el fin de la ampliación.

La salida temporal, cierre, falta de vencimiento o historial inválido no tienen
avisos activos. Un retorno válido recalcula el vencimiento y sus avisos. Las fechas
de aviso ya transcurridas no se programan retroactivamente. Las consultas filtran
planes que hayan vencido con el paso del día usando la fecha de Guatemala.

## Entorno y entrega

Solo `servamar-postgres-test`, rama Neon `br-green-band-arsmtoxc`, base
`servamar_demo`, esquema `servamar_test`, datos ficticios. La migración V96 retira
el bloqueo de V95, conserva los datos y crea `v96_notification_schedule`. Esta
tabla es un calendario de pruebas separado de los eventos de entrega: no hay
SMTP, push, trabajador ni tarea programada. El endpoint de envío sigue devolviendo
403; los ajustes antiguos de envío permanecen deshabilitados. Crear un plan no
envía mensajes ni autoriza envíos futuros.

La vista previa muestra las fechas actuales. `/notifications/plan` devuelve el
calendario por email/push/Windows y su historial, con `delivery_enabled=false`.
Los planes son datos derivados: se eliminan junto a un expediente sin otras
dependencias; los eventos reales y demás registros siguen protegidos por RESTRICT.

La migración es idempotente y crea planes para los expedientes ficticios existentes.
El ejecutor actual sustituye la migración V95 por V96 para no volver a aplicar su
regla obsoleta. Las pruebas V96 sustituyen los resultados esperados de V95 y cubren
ingreso → ampliación → depósito, correcciones y eliminación, fechas manuales,
salida/retorno, deduplicación, enviados, fechas pasadas, concurrencia por versión,
reversión transaccional y migración repetida. Las regresiones V89–V94 continúan.
