# SERVAMAR V72 — preparación de migración operativa

**Estado:** fase de preparación y validación. NO es un cambio de motor de la
aplicación. La interfaz sigue utilizando SQLite para los expedientes operativos,
y Neon sigue ejecutando el laboratorio ficticio.

## Qué incluye

- Verificación del respaldo completo generado en `/api/backup/full`.
- Comprobación de hashes SHA-256 del manifiesto y de cada permiso.
- Comprobación de integridad SQLite, referencias entre tablas y presencia de
  todos los documentos asociados.
- Restauración en una carpeta NUEVA, sin sobrescribir los expedientes actuales.
- Importación optativa y transaccional a tablas separadas de Neon, con
  recuentos y documentos binarios. Los registros se almacenan como JSONB para
  preservación, no como un motor operativo ya habilitado.

## Uso local (en equipo confiable)

Instalar Python y las dependencias de `requirements.txt` en el equipo.
Descargar el respaldo completo desde una instalación operativa autorizada.
**No subir expedientes de clientes a GitHub ni compartirlos por el chat.**

Verificar:

```bash
python operational_backup.py --verify "servamar_respaldo_completo_YYYYMMDD_HHMMSS.zip"
```

Restaurar a una carpeta NUEVA:

```bash
python operational_backup.py --restore-to "./recuperacion_prueba" "servamar_respaldo_completo_YYYYMMDD_HHMMSS.zip"
```

En una fase posterior, solo después de autorizar el manejo de expedientes
reales en una infraestructura segura, configurar la variable privada
`SERVAMAR_OPERATIONAL_STAGING_URL` en el equipo y ejecutar:

```bash
python operational_backup.py --stage-neon "servamar_respaldo_completo_YYYYMMDD_HHMMSS.zip"
```

**No activar todavía esa última orden con información real.** La prueba de
persistencia de adjuntos, cuotas, acceso, cifrado y recuperación de desastres
debe completarse antes. Neon gratuito tiene límites de almacenamiento.

## Restricciones deliberadas

- No cambia `BOATS_DB`, `SERVAMAR_PUSH_DATABASE_URL` ni las variables de Render.
- No envía correos, no altera movimientos ni elimina filas de origen.
- No importa copias con documentos faltantes o alterados.
- No sobrescribe una carpeta de restauración existente.
- La importación a Neon se identifica por el SHA-256 del ZIP y es idempotente.
- El esquema de Neon preparado es **solo de staging**: no hay lecturas ni
  escrituras operativas dirigidas a él.

## Siguiente fase

1. Probar restauración con un respaldo ficticio completo y sus documentos.
2. Desarrollar adaptador operacional PostgreSQL y pruebas de equivalencia
   de cálculos, ediciones, historial, reportes y notificaciones.
3. Separar los documentos a almacenamiento privado durable con backups.
4. Verificar restauración y conmutación reversible en entorno de ensayo.
5. Habilitar datos reales únicamente tras validar seguridad y capacidad.

## Límite confirmado de Neon gratuito

El proyecto de pruebas ya contiene una instantánea manual de V67. Intentar
crear una segunda instantánea devolvió `snapshots limit exceeded`. No se
eliminó la instantánea existente. **No existe todavía un respaldo automático
externo y verificado de Neon.** La función de restauración V72 se aplica a
respaldos operativos ZIP, no sustituye un plan de recuperación integral de
PostgreSQL.
