# V94: reglas confirmadas y base funcional de pruebas

Alcance: únicamente `servamar-postgres-test` y la rama Neon
`br-green-band-arsmtoxc`, base `servamar_demo`, esquema `servamar_test`.
La aplicación original, los datos reales y los envíos quedan fuera del cambio.

## Criterios confirmados por Gerson

| Operación | Cálculo |
| --- | --- |
| Ingreso | Fecha de ingreso + 90 días transcurridos |
| Ampliación | Vencimiento vigente + 9 meses calendario; una por ciclo |
| Depósito | Fecha del depósito + 12 meses calendario |
| Retorno tras 0–90 días fuera | Conserva el permiso y suma todos los días fuera al vencimiento anterior |
| Más de 90 días fuera | Cierra el permiso desde el día 91; el contador visible se detiene en 90 |
| Salida con permiso vencido | Cierra el permiso; nuevo ingreso tras cumplir 90 días fuera |
| Recordatorios | 30, 15 y 1 días antes del vencimiento; solo vista previa |

El día de salida es día 0. La diferencia entre las dos fechas determina los días
fuera. El día 90 aún está dentro del plazo permitido: `días_fuera <= 90`
conserva el permiso. El cierre por exceso utiliza `días_fuera > 90`, desde el
día 91. Una salida el 05/01/2026 con retorno el 05/04/2026 acumula exactamente
90 días y añade 90 al vencimiento previo. Esto no reabre un permiso que ya estaba
cerrado ni cambia la regla especial de una salida con permiso vencido.

Los 90 días iniciales no se sustituyen por tres meses. Ejemplo:
04/11/2026 + 90 días = 02/02/2027; con ampliación = 02/11/2027.
El primer recordatorio de ese vencimiento corresponde al 03/10/2027, exactamente
30 días antes. Los meses calendario se ajustan al último día del mes destino
cuando no existe el mismo número de día, incluidos años bisiestos.

## Funcionamiento

Los expedientes anteriores conservan `calculation_mode=manual` y sus fechas.
Los nuevos expedientes creados en la consola seleccionan por defecto
«Calcular según movimientos». Para activar el cálculo en uno anterior, abrir
«Editar», revisar la fecha de ingreso y elegir ese modo. Un historial incoherente
impide el cambio y conserva todos los valores previos.

Agregar, editar o eliminar un movimiento reproduce el historial completo dentro
de la misma transacción. No duplica días añadidos; cualquier incoherencia revierte
movimiento, versión, proyección y auditoría. Se rechazan retornos sin salida,
salidas duplicadas, ampliaciones repetidas, movimientos futuros y salidas desde
depósito. Se puede corregir el historial de un expediente manual antes de activar
su cálculo. Los eventos del mismo día se ordenan por identificador.

La lectura calcula el cierre al pasar al día 91 según la fecha de Guatemala, sin
trabajos programados. La búsqueda por etapa incluye ese cierre. Las fichas,
búsquedas, CSV/Excel/PDF y vistas previas usan el mismo cálculo. Un expediente que
requiera revisión no genera recordatorios.

## Módulos disponibles desde V93

- Movimientos editables y eliminables con control de versión y auditoría.
- Contactos editables y contacto principal por expediente.
- PDF/JPG/PNG privados hasta 2 MB, validación, descarga autenticada,
  archivo/restauración y detección de duplicados; archivos guardados en PostgreSQL.
- Búsqueda por embarcación, capitán, matrícula y registro; filtros de etapa,
  fechas de ingreso/vencimiento, mes y período.
- Exportación CSV, Excel y PDF; se exige reducir filtros cuando supera 1000 filas.
- Vista previa bilingüe de recordatorios. El endpoint de envío devuelve 403.

No se configura SMTP, push, cola de entrega ni tareas automáticas. V94 no modifica
el servicio original ni importa información de clientes.

## Pruebas y migración

`test_v94_permits.py` cubre retornos de 0, 37, 89, 90 y 91 días; cambio de mes,
bisiestos, depósito, múltiples salidas, cierre diario, nuevo ingreso, edición y
eliminación, reversión transaccional, cambio de modo, búsquedas, exportación y
recordatorios de 30 días. Las suites V89–V93 siguen en CI con PostgreSQL 18.
La prueba Chromium verifica las pantallas móvil y escritorio, el modo calculado,
edición, documentos, vista previa y descarga Excel con API ficticia interceptada.

Aplicar `migrations/v94_confirmed_permits.sql` en el esquema de pruebas antes del
despliegue. Es aditiva e idempotente: únicamente añade el modo de cálculo con
valor inicial manual. `postgres_test_migrate.py` incluye las migraciones V90–V94.
El acceso autenticado al servicio desplegado requiere la contraseña de pruebas;
los resultados de CI no equivalen a una sesión autenticada en Render.
