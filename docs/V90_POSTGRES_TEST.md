# SERVAMAR V90 — gestión de embarcaciones ficticias

Aplicación independiente: `postgres_test_app.py`. Servicio: https://servamar-postgres-test.onrender.com.
Neon: proyecto `broad-paper-38854135`, rama `br-green-band-arsmtoxc`, base `servamar_demo`, esquema `servamar_test`.

## Funciones

- Alta y edición de matrícula ficticia, nombre, capitán, fecha de ingreso y vencimiento manual.
- Fechas de la interfaz en `dd/mm/yyyy`, con validación de calendario. La API conserva fechas ISO en respuestas y acepta ambas entradas.
- Historial cronológico y registro de ingreso, ampliación, depósito, salida, retorno y cierre, con fecha, descripción y vencimiento de referencia opcional.
- Los movimientos NO proyectan etapa ni vencimiento: esas reglas siguen pendientes de validación. No envían correos ni notificaciones.
- Eliminación únicamente sin movimientos ni alertas vinculadas, escribiendo la matrícula exacta. Las claves foráneas mantienen `ON DELETE RESTRICT`; nunca se eliminan hijos ni se usa cascada.
- Auditoría transaccional de alta, edición, movimiento y eliminación; conserva los datos anteriores de registros eliminados. No hay interfaz para borrar auditoría.
- Versiones y bloqueo de fila impiden sobrescribir cambios concurrentes y duplicar movimientos por reenvío del mismo formulario. Secuencias PostgreSQL evitan colisiones de identificadores.
- HTTPS, autenticación existente, protección CSRF y comprobación explícita del endpoint de la rama de pruebas.

## Despliegue

Conservar las variables privadas y el comando `gunicorn postgres_test_app:app --bind 0.0.0.0:$PORT` del servicio de pruebas.
Aplicar `python postgres_test_migrate.py` con las mismas variables `SERVAMAR_PG_TEST_*`, usando la conexión **directa**, sin `-pooler`, exclusivamente de la rama indicada.
La migración es aditiva y repetible: agrega secuencias, versión y auditoría sin modificar datos existentes ni claves foráneas.
Aplicarla antes de publicar V90; evitar altas en V89 durante ese intervalo. Si las hubo, volver a ejecutar la migración para sincronizar secuencias antes de permitir nuevas altas V90.

Publicar el código revisado en GitHub y esperar el despliegue automático de `servamar-postgres-test`. Confirmar `live`, `/healthz` con `version=V90`, autenticación y consulta real de PostgreSQL.
`/healthz` es una comprobación de proceso/configuración; la consulta autenticada de embarcaciones verifica la base.
La aplicación original `app.py`, sus recursos compartidos, SQLite, `requirements.txt`, `render.yaml` y el servicio original no se cambian.

## Pruebas reproducibles

```sh
python -m unittest discover -s tests -p 'test_v89_*.py' -v
python -m unittest discover -s tests -p 'test_v90_*.py' -v
node --check static/postgres-test.js
```

Para integración, definir `V90_TEST_POSTGRES_URL` con una conexión PostgreSQL de pruebas. Se crea un esquema `v90_ci_<uuid>` aislado, se prueba la migración y se limpia únicamente ese esquema; no se usa el esquema de la aplicación para las pruebas automatizadas.
El workflow V90 usa PostgreSQL 18 efímero en GitHub Actions, sin secretos de Neon.
Las pruebas cubren validación, duplicados, fechas, autenticación, CSRF, conflictos, auditoría, reversión transaccional, integridad referencial y operaciones simultáneas.

La API requiere `X-CSRF-Token` (meta de la página autenticada) en escrituras. Edición, eliminación y movimientos requieren la versión actual del registro. Un conflicto devuelve HTTP 409: recargar y revisar, sin reintento automático.
