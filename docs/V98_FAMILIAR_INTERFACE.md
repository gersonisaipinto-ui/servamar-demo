# V98 · Recuperar el aspecto anterior de SERVAMAR

La migración a Neon no exige cambiar la interfaz. Esta versión adapta al entorno
PostgreSQL la identidad visual de `templates/index.html` y `static/style.css`:
encabezado azul degradado con ancla, pestañas por colores, paneles desplegables y
tablas compactas que se convierten en fichas en el teléfono.

## Navegación

- **Inicio:** resumen desplegable y control de vencimientos de los próximos 30 días.
- **Nuevo ingreso:** formulario actual con fechas dd/mm/yyyy, calendario y modo de cálculo.
- **Buscar:** filtros, resultados y lista desplegable de todos los expedientes.
- **Avisos:** acceso al calendario de cada embarcación y vista previa del correo.
- **Descargar control:** filtros independientes, vista previa tabular y Excel/PDF/CSV.
  «Llevar filtros a reportes» copia la búsqueda y permite revisarla antes de descargar.
- **Expediente:** movimientos, contactos, documentos y calendario. Cerrar vuelve a
  la sección desde la que se abrió.

No se reutilizan los endpoints ni los scripts de la aplicación original. Solo se
modifican los archivos de la consola PostgreSQL y sus pruebas. Las fórmulas y
transacciones V94/V96 se conservan: 90 días + 9 meses calendario, retorno en el día
90 inclusive y avisos de 30/15/1 días asociados al vencimiento actual.

No hay migración de datos ni modificación de Neon. Solo datos ficticios. Correos
y notificaciones reales siguen desactivados. OCR y transporte de envíos siguen
pendientes, según el estado funcional documentado en V97.

## Validación

Las suites de PostgreSQL se ejecutan junto con una prueba Chromium que recorre las
cinco secciones, el expediente, formularios, documentos, planes de avisos, la
transferencia de filtros y la descarga de reportes. Comprueba diseños a 320, 390 y
1440 píxeles y guarda capturas de la interfaz anterior y V98 como artefactos de CI.
Las API de la prueba de navegador utilizan datos ficticios simulados; las pruebas
de base de datos usan PostgreSQL 18 efímero.
