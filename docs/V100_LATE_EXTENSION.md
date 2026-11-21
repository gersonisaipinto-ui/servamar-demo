# V100 · Autorización posterior y base de la ampliación

Regla confirmada por el usuario el 21/11/2026: se acepta una ampliación autorizada después del vencimiento. Los nueve meses calendario se suman al último vencimiento del permiso, incluidos los días de salidas temporales ya añadidos por retornos válidos. La autorización no inicia un nuevo plazo.

## Cálculo y pantalla
- El motor distingue fecha de autorización, vencimiento que inicia el plazo, días añadidos antes de ampliar y vencimiento resultante.
- La vista previa y el expediente muestran la operación y la diferencia entre autorización e inicio del plazo.
- Se conserva la autorización futura confirmada para ST-DEMO-004 como referencia del entorno ficticio, con indicación visible. Esta excepción afecta únicamente a ampliaciones; no permite ingresos, salidas, retornos, depósitos o cierres futuros.
- Siguen rechazándose ampliaciones duplicadas, salidas abiertas, permisos cerrados y ampliaciones desde depósito. Un depósito sigue necesitando permiso vigente.
- Si la autorización llega después de los nueve meses, no desplaza el vencimiento ni otorga nueve meses nuevos: el permiso permanece vencido.
- Corregir un retorno o borrar una ampliación reproduce el historial y recalcula avisos 30/15/1, cancelando los anteriores sin envíos.

## Casos de prueba
Ingreso 17/08/2026 → vencimiento inicial 15/11/2026. Autorización 16/12/2026 → vence 15/08/2027.
El mismo ingreso, con salida 20/08/2026 y retorno 26/09/2026 (37 días), vence inicialmente 22/12/2026. Autorización 15/01/2027 → vence 22/09/2027.
Se prueban retornos de 0/37/89/90 días, cierre al exceder 90, varias salidas, autorizaciones posteriores, edición y eliminación con planes de avisos. El navegador usa Flask y PostgreSQL efímero sin simular respuestas API.

Solo aplicación PostgreSQL de pruebas. Sin migración estructural, importaciones ni cambios en la aplicación original. Envíos desactivados. La corrección puntual de ST-DEMO-004 conserva sus fechas confirmadas y su auditoría.
