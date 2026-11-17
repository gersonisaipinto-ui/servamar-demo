# SERVAMAR V93 — base funcional de pruebas

Esta versión depende del PR #27 (V92 corregido). Solo utiliza `postgres_test_app.py`, la rama Neon `br-green-band-arsmtoxc`, base `servamar_demo`, esquema `servamar_test` y el servicio `servamar-postgres-test`. No modifica `app.py`, los activos de la aplicación original, `requirements.txt`, `render.yaml`, SQLite ni tareas programadas. No importa registros reales.

## Funciones listas para probar

- Embarcaciones: alta, edición y número de registro; autenticación, HTTPS, CSRF, bloqueo y control de versión.
- Movimientos: alta, edición, eliminación confirmada por matrícula, orden cronológico, último movimiento en la interfaz, auditoría anterior/posterior y transacción completa. Los cambios no recalculan ni sobrescriben etapa o vencimiento.
- Contactos: alta, edición, eliminación y un solo contacto principal. Se corrige la restricción de auditoría de V90 que rechazaba acciones de V91. La definición reproducible de V91 ahora está en el repositorio.
- Documentos ficticios: PDF/JPG/PNG de hasta 2 MB, comprobación del contenido, nombre seguro, hash SHA-256, descarga autenticada, detección de duplicados y archivo/restauración. El contenido se conserva en PostgreSQL para sobrevivir a reinicios y despliegues. Los documentos anteriores sin contenido se muestran como pendientes de carga. No se incluye OCR en esta versión.
- Búsquedas: nombre, capitán, matrícula, registro, mes y período de ingreso o vencimiento. Fechas dd/mm/yyyy; orden por vencimiento. La búsqueda trata `%` y `_` literalmente.
- Reportes: CSV protegido contra fórmulas, XLSX con celdas de texto y PDF con encabezados y páginas. Comparten filtros con la vista previa. Más de 1000 resultados exige acotar filtros: nunca se exporta un archivo recortado silenciosamente.
- Notificaciones: borrador bilingüe y fechas de referencia 30/15/1 días, sin envío ni creación de cola. El endpoint de envío devuelve 403 incluso si existe una variable externa que intente habilitarlo. No hay transporte, cron ni integración SMTP/push.

## Decisiones pendientes: no activar cálculos definitivos

Ingreso ficticio del **04/11/2026**:

| Regla | Vencimiento inicial |
| --- | --- |
| Ingreso + 90 días transcurridos | 02/02/2027 |
| Ingreso + 3 meses calendario | 04/02/2027 |

La ampliación de nueve meses también necesita una base inequívoca: nueve meses después del plazo de 90 días produciría 02/11/2027; el aniversario del ingreso o tres meses + nueve meses produciría 04/11/2027. El ejemplo anterior del usuario favorece el aniversario, pero no se impone sin confirmación.

Confirmar además el tratamiento del retorno **exactamente al día 90** (el criterio previo decía “antes de 90” y cierre “si excede 90”) y si “un mes antes” del recordatorio significa mes calendario o 30 días. Esta entrega conserva vencimientos manuales y presenta 30/15/1 únicamente como referencia.

No se ha implementado un motor de permisos definitivo. Quedan pendientes las transiciones, la suma de ausencias, los cierres y la elegibilidad de reingreso hasta resolver las reglas. El módulo de documentos no realiza extracción automática.

## Migración y despliegue

Antes de desplegar V93, ejecutar `python postgres_test_migrate.py` con las variables privadas de pruebas y el endpoint directo fijado. Se ejecutan V90, V91 y V93 en una única transacción; son repetibles. V93 amplía la restricción de auditoría, añade fecha de archivo y tabla de contenido. No borra registros, documentos, ni alertas.

La migración no se ejecuta automáticamente durante peticiones web. Una versión anterior puede seguir usando la base ampliada. No ejecutar una reversión de esquema para volver al código previo.

Confirmar en Render el espacio de trabajo y servicio exactos antes de integrar y desplegar. Mantener el comando `gunicorn postgres_test_app:app --bind 0.0.0.0:$PORT` y las credenciales existentes. Tras el despliegue, comprobar estado `live`, commit, `/healthz` con V93 y una consulta autenticada. `/healthz` informa del proceso y la configuración, no sustituye una consulta real a PostgreSQL.

## Pruebas

El workflow `.github/workflows/v90-postgres-test.yml` utiliza PostgreSQL 18 efímero, sin credenciales Neon, y ejecuta las suites V89/V90/V92/V93. Las pruebas V93 generan un esquema temporal `v93_ci_<uuid>`, aplican las migraciones reales y eliminan únicamente sus propias tablas al finalizar. Cubren conflictos, aislamiento entre expedientes, auditoría y rollback, documentos, formatos de exportación, límites, búsquedas y ausencia de envíos.

No ejecutar la suite de integración sobre un entorno real. `V90_TEST_POSTGRES_URL` debe apuntar a PostgreSQL de pruebas.
