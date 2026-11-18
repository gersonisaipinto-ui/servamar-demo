# V99 · Ampliaciones y vencimiento visible

## Problema corregido
Los expedientes anteriores conservaban `calculation_mode=manual`. Registrar una ampliación añadía el historial, pero no cambiaba etapa ni vencimiento. La consola tampoco mostraba la fecha calculada antes de guardar, y exigía una fecha de autorización que antes era opcional.

## Comportamiento
- En un expediente manual, el formulario ofrece aplicar el cálculo al guardar, activado inicialmente y explicado junto a la vista previa. Desactivarlo conserva explícitamente el registro de referencia y su fecha manual.
- La vista previa protegida valida el mismo historial y motor utilizados al guardar. No escribe movimientos, versiones, auditoría ni planes. Identifica la fecha efectiva del movimiento y cualquier cambio de modo.
- Guardar aplica modo, historial, etapa, vencimiento, auditoría, versión y cancelación/reprogramación de avisos en una sola transacción. Los errores revierten todo.
- Al elegir ampliación se muestra el vencimiento calculado y la operación: vencimiento inicial más nueve meses calendario. La autorización puede omitirse; la vista previa indica la fecha de hoy en Guatemala que se registrará.
- Nuevo ingreso vuelve a mostrar el vencimiento inicial calculado (90 días). Los errores de movimiento se ven junto al formulario, también en móvil.
- Se mantienen 90 días iniciales, nueve meses calendario de ampliación, doce meses desde ingreso a depósito, retorno hasta el día 90 inclusive y avisos a 30/15/1 días del vencimiento vigente.
- No se cambian automáticamente expedientes anteriores con fechas futuras, ampliaciones duplicadas o secuencias inválidas: se informa el error y se conserva el historial para corregirlo.

## Verificación
Pruebas PostgreSQL: vista previa sin efectos, conversión de expediente manual, autorización opcional, edición de ampliación existente sin duplicarla, cancelación/reprogramación, rechazo de duplicados/fechas futuras/versiones obsoletas y rollback ante fallo de auditoría.
Prueba adicional de navegador contra Flask y PostgreSQL efímero (sin simular respuestas API): ampliación desde expediente manual, vista previa, guardado, recarga, rechazo de duplicado, depósito y planes de avisos. Se generan capturas en móvil y escritorio.
Se conserva la suite anterior de módulos y navegación responsive.

## Alcance
Únicamente la aplicación PostgreSQL de pruebas. Sin migración ni modificación de registros existentes en Neon. Sin importaciones, correos, push, tareas programadas ni cambios a la aplicación original.
