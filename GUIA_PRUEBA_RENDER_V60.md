# SERVAMAR V60 — demostración gratuita en Render

## Propósito
Este paquete permite una demostración exclusivamente de lectura con tres embarcaciones ficticias. La base SQLite está en `/tmp` y **se pierde cuando Render suspende o reinicia el servicio**. No importar ni registrar expedientes reales, PDFs o datos personales. Las peticiones POST/PUT/PATCH/DELETE se bloquean y ningún envío de correo o push se activa.

## Publicación (sin modificar Pattern Alert)
1. Crear repositorio **privado nuevo** `servamar-demo` en GitHub y subir solamente el contenido de esta carpeta, no el ZIP de datos ni archivos `correo_local.env`, SQLite, Excel o PDF.
2. Render > New > Blueprint; seleccionar el repositorio privado y `render.yaml`. Revisar que figure **solo un Web Service free**, sin disco persistente, cron ni base PostgreSQL.
3. Render pedirá `APP_USERNAME` y `APP_PASSWORD` (contraseña nueva de **al menos 16 caracteres**). No publicar ni compartir la contraseña. Aprobar únicamente si todos los recursos son gratuitos.
4. Abrir la URL HTTPS de Render y probar desde Windows y Android. Puede tardar un minuto al despertar.
5. El servicio es SOLO lectura. No tiene datos verdaderos y no prueba la persistencia, movimientos simultáneos, PDFs ni envío real de correos/FCM.

## Seguridad y limitaciones
- No usar credenciales del servicio de oficina.
- No subir archivos de clientes ni secretos a GitHub.
- No usar esta demostración como producción.
- No envía emails ni notificaciones, no sustituye las tareas Windows.
- Render free no ofrece disco persistente y suspende servicios inactivos.
