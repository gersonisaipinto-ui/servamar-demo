# V97 · Consola de pruebas operativa

Entorno exclusivo: `servamar-postgres-test.onrender.com`, rama Neon
`br-green-band-arsmtoxc`, esquema `servamar_test`. Solo registros y documentos
ficticios. No modifica `app.py` ni la aplicación original. No requiere migración.

## Cambios

- Inicio con embarcación, capitán y plazo de los próximos 30 días, ordenados por
  vencimiento. El resto de expedientes se consulta por búsqueda o desplegando
  «Todos los registros de prueba».
- Búsqueda explícita por texto, etapa, mes, ingreso o vencimiento y período.
  Los filtros se aplican también a las descargas CSV, Excel y PDF.
- Fechas `dd/mm/yyyy`: barras al escribir ocho dígitos, calendario nativo, sincronización
  al editar/restablecer, validación de fechas imposibles y bloqueo del vencimiento
  manual cuando se utiliza el cálculo por movimientos.
- Calendario visible de avisos a 30, 15 y 1 días antes del vencimiento actual.
  Agrupa correo, Android/push y Windows cuando coinciden fecha y estado; conserva
  aparte cancelados, fechas pasadas y constancias de envío históricas. El calendario
  se vuelve a consultar después de cada cambio de movimiento.
- La planificación no ejecuta envíos. No hay cron, trabajador, SMTP ni transporte
  push activado; el endpoint de envío sigue rechazando solicitudes.

## Base funcional disponible en pruebas

Movimientos editables/eliminables con auditoría y control de versiones; cálculo
90 días + 9 meses calendario, retorno en el día 90 inclusive y depósito de 12 meses;
contactos; documentos privados PDF/JPG/PNG, descarga y archivo/restauración;
búsqueda y reportes; vista previa bilingüe y planificación de avisos según el
vencimiento vigente. V96 reemplaza la suspensión permanente introducida en V95.

## Validación

La integración continua ejecuta las suites V89/V90/V92/V93/V94/V96 sobre PostgreSQL
18 efímero y la prueba Chromium móvil/escritorio `tests/ui_v93_smoke.py`. Esta
última intercepta las API con datos ficticios: valida interfaz, fechas, filtros,
planes vigentes/cancelados, cambios de movimientos, documentos y descarga Excel.
No sustituye una prueba de sesión autenticada en Render ni una entrega real de correo.

## Pendiente

- OCR de permisos: extracción, revisión y confirmación de campos desde un archivo
  ficticio antes de guardar. La carga/descarga actual no extrae datos.
- Transporte y prueba de entrega real: requieren autorización expresa y destinatarios
  de prueba; no están activados. La planificación ya se recalcula y cancela avisos
  obsoletos dentro de la misma transacción del cambio de vencimiento.
- Validación operativa por el usuario con su sesión de pruebas en PC y Android.
  La salud pública de Render confirma versión/configuración, no los flujos autenticados.
