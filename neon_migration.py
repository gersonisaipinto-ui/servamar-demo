"""One-time, non-destructive PostgreSQL DEMO + push migration to Neon.

Runs only with explicit SERVAMAR_NEON_MIGRATE_ON_BOOT=YES. Source stays
untouched. Target must be empty; migration commits atomically after
row counts and full CSV-stream checksums match a consistent source snapshot.
No credentials, device endpoints, or VAPID keys are logged.
"""
from __future__ import annotations

import hashlib
import json
import os

# All identifiers below are fixed application-owned names, never user inputs.
TABLES = {
    "servamar_demo_vessels": ("id", "registration", "vessel_name", "captain", "stage", "entry_date", "movement_date", "due_date", "notes", "version", "created_at", "updated_at"),
    "servamar_demo_vessel_audit": ("id", "vessel_id", "action", "registration", "at_time"),
    "servamar_demo_movements": ("id", "vessel_id", "kind", "event_date", "stage_before", "due_before", "stage_after", "due_after", "created_at"),
    "servamar_demo_movement_corrections": ("id", "vessel_id", "movement_id", "action", "registration", "before_state", "after_state", "at_time"),
    "servamar_push_subscriptions": ("id", "content"),
    "servamar_push_settings": ("id", "pem"),
    "servamar_push_daily_delivery": ("day", "status", "count", "recipients", "completed_at"),
    "servamar_push_daily_targets": ("day", "sub_id"),
    "servamar_push_checks": ("id", "day", "status", "alerts", "accepted", "failed", "checked_at"),
}

TABLE_DDL = (
    """CREATE TABLE IF NOT EXISTS servamar_demo_vessels
    (id BIGSERIAL PRIMARY KEY, registration TEXT NOT NULL UNIQUE,
    vessel_name TEXT NOT NULL, captain TEXT NOT NULL, stage TEXT NOT NULL,
    entry_date DATE NOT NULL, movement_date DATE NOT NULL, due_date DATE,
    notes TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
    """CREATE TABLE IF NOT EXISTS servamar_demo_vessel_audit
    (id BIGSERIAL PRIMARY KEY, vessel_id BIGINT NOT NULL, action TEXT NOT NULL,
    registration TEXT NOT NULL, at_time TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
    """CREATE TABLE IF NOT EXISTS servamar_demo_movements
    (id BIGSERIAL PRIMARY KEY, vessel_id BIGINT NOT NULL, kind TEXT NOT NULL,
    event_date DATE NOT NULL, stage_before TEXT NOT NULL, due_before DATE,
    stage_after TEXT NOT NULL, due_after DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
    """CREATE TABLE IF NOT EXISTS servamar_demo_movement_corrections
    (id BIGSERIAL PRIMARY KEY, vessel_id BIGINT NOT NULL,
    movement_id BIGINT NOT NULL, action TEXT NOT NULL, registration TEXT NOT NULL,
    before_state JSONB NOT NULL, after_state JSONB NOT NULL,
    at_time TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
    """CREATE TABLE IF NOT EXISTS servamar_push_subscriptions
    (id TEXT PRIMARY KEY, content TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS servamar_push_settings
    (id TEXT PRIMARY KEY, pem TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS servamar_push_daily_delivery
    (day TEXT PRIMARY KEY, status TEXT NOT NULL, count INTEGER NOT NULL,
    recipients INTEGER NOT NULL, completed_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS servamar_push_daily_targets
    (day TEXT NOT NULL, sub_id TEXT NOT NULL, PRIMARY KEY(day,sub_id))""",
    """CREATE TABLE IF NOT EXISTS servamar_push_checks
    (id BIGSERIAL PRIMARY KEY, day TEXT NOT NULL, status TEXT NOT NULL,
    alerts INTEGER NOT NULL, accepted INTEGER NOT NULL, failed INTEGER NOT NULL,
    checked_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS servamar_migration_receipts
    (id TEXT PRIMARY KEY, source_name TEXT NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    counts JSONB NOT NULL, checksum TEXT NOT NULL)""",
)

SERIAL_TABLES = (
    "servamar_demo_vessels", "servamar_demo_vessel_audit",
    "servamar_demo_movements", "servamar_demo_movement_corrections",
    "servamar_push_checks",
)
MIGRATION_ID = "render-demo-to-neon-v67"


def _copy_sql(table, columns):
    fields = ",".join(columns)
    return (
        f"COPY (SELECT {fields} FROM {table} ORDER BY {fields}) TO STDOUT WITH (FORMAT CSV)",
        f"COPY {table} ({fields}) FROM STDIN WITH (FORMAT CSV)",
    )


def _digest_tables(db):
    digest = hashlib.sha256()
    with db.cursor() as cur:
        for table, columns in TABLES.items():
            digest.update((table + "\\n").encode())
            read_sql, _ = _copy_sql(table, columns)
            with cur.copy(read_sql) as reader:
                for block in reader:
                    digest.update(block)
    return digest.hexdigest()


def _counts(db):
    return {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in TABLES}


def migrate_demo(source_url, target_url):
    import psycopg

    if not source_url or not target_url or source_url == target_url:
        raise RuntimeError("La migración necesita dos conexiones PostgreSQL distintas")
    with psycopg.connect(source_url, connect_timeout=15) as source:
        with psycopg.connect(target_url, connect_timeout=15) as target:
            # Single consistent snapshot; the old database is never modified.
            source.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            source.execute("SET LOCAL TIME ZONE 'UTC'")
            target.execute("SET LOCAL TIME ZONE 'UTC'")
            target.execute("SELECT pg_advisory_xact_lock(671267)")
            for ddl in TABLE_DDL:
                target.execute(ddl)
            receipt = target.execute(
                "SELECT counts,checksum FROM servamar_migration_receipts WHERE id=%s",
                (MIGRATION_ID,),
            ).fetchone()
            if receipt:
                return {"status": "already_migrated", "counts": receipt[0],
                        "checksum": receipt[1]}
            dest_before = _counts(target)
            if any(dest_before.values()):
                raise RuntimeError("Neon ya contiene registros; no se sobrescribirá ninguna tabla")
            original_counts = _counts(source)
            source_digest = hashlib.sha256()
            with source.cursor() as src, target.cursor() as dst:
                for table, columns in TABLES.items():
                    source_digest.update((table + "\\n").encode())
                    select_sql, insert_sql = _copy_sql(table, columns)
                    with src.copy(select_sql) as reader:
                        with dst.copy(insert_sql) as writer:
                            for block in reader:
                                source_digest.update(block)
                                writer.write(block)
            dest_after = _counts(target)
            if dest_after != original_counts:
                raise RuntimeError("La migración no coincide con la cantidad de registros original")
            if source_digest.hexdigest() != _digest_tables(target):
                raise RuntimeError("La verificación de integridad de datos no coincide")
            for table in SERIAL_TABLES:
                highest = target.execute(f"SELECT COALESCE(MAX(id),0) FROM {table}").fetchone()[0]
                target.execute(
                    "SELECT setval(pg_get_serial_sequence(%s,'id'),%s,%s)",
                    (table, highest or 1, bool(highest)),
                )
            target.execute(
                """INSERT INTO servamar_migration_receipts
                (id,source_name,counts,checksum) VALUES(%s,%s,%s::jsonb,%s)""",
                (MIGRATION_ID, "Render PostgreSQL DEMO",
                 json.dumps(original_counts), source_digest.hexdigest()),
            )
            # Connection context commits only after every check passes.
            return {"status": "migrated", "counts": original_counts,
                    "checksum": source_digest.hexdigest()}


def migrate_on_boot():
    if os.getenv("SERVAMAR_DEMO_MODE", "").upper() != "YES":
        raise RuntimeError("La migración a Neon solo se admite en modo DEMO")
    if os.getenv("SERVAMAR_DEMO_WRITES_FROZEN", "").upper() != "YES":
        raise RuntimeError("Primero debes bloquear las escrituras DEMO")
    result = migrate_demo(
        os.getenv("SERVAMAR_PUSH_DATABASE_URL", ""),
        os.getenv("SERVAMAR_NEON_DATABASE_URL", ""),
    )
    # No secrets, web-push endpoints, or personal data in the logs.
    print("SERVAMAR_V67_NEON_MIGRATION " + json.dumps(result, sort_keys=True), flush=True)
    return result
