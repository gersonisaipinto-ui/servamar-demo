# V95: suspensión al registrar ampliación o depósito

Regla solicitada: registrar una **ampliación** o un **depósito** desactiva los
correos y las notificaciones automáticos de esa embarcación. Funciona tanto en
modo manual como calculado y también al editar otro movimiento para convertirlo
en ampliación o depósito.

La suspensión se guarda en el expediente. Deshabilita sus ajustes de alertas y
cancela recordatorios automáticos pendientes o fallidos para email, push y
Windows. Conserva los eventos enviados y los eventos manuales. No modifica los
avisos de otras embarcaciones. Movimiento, suspensión, cancelaciones, versión y
auditoría se guardan en una sola transacción; si falla, se revierten juntos.

Editar, borrar el movimiento o cambiar otros datos no reactiva los envíos. No se
añade un control para reactivarlos. El estado y el motivo se muestran en el
expediente. La vista previa manual continúa disponible, sin calendario automático
para un expediente suspendido.

La migración idempotente `v95_stop_automatic_notices.sql` aplica también la regla a
expedientes ficticios que ya tengan una ampliación o depósito y aumenta su versión
para evitar sobrescrituras desde una pantalla antigua. Se ejecuta únicamente en
la rama Neon `br-green-band-arsmtoxc`, base `servamar_demo`, esquema `servamar_test`.

En este entorno el transporte de correo y notificaciones continúa bloqueado
globalmente. La regla deja además guardada la suspensión individual; no habilita
SMTP, push, trabajadores ni tareas programadas. La aplicación original no cambia.

Pruebas: ambos tipos de movimiento en ambos modos, los tres canales, cancelación
de pendientes y reintentos, conservación de enviados/manuales, aislamiento por
embarcación, edición/eliminación, versiones obsoletas, historial inválido,
reversión por error de auditoría e idempotencia de la migración. Se mantienen las
regresiones V89–V94 y la prueba de interfaz móvil/escritorio.

Esta regla sustituye la generación de recordatorios tras ampliación/depósito
descrita en V94; la regla de 30, 15 y 1 días sigue definida para otros expedientes.
