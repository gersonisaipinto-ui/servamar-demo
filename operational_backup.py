"""SERVAMAR V72: verify, restore and stage an operational full backup.

This is an OFFLINE, explicit command-line utility. It never changes the running
SQLite application, Neon demo tables or Render configuration. No network action
is performed unless --stage-neon is explicitly selected.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path

FORMAT = "servamar-full-backup-v1"
MAX_TOTAL_BYTES = 200 * 1024 * 1024
MAX_FILES = 1500
DOC_NAME = re.compile(r"private_permits/[0-9a-f]{32}\.(?:pdf|jpg|jpeg|png|webp)\Z")
TABLES = (
    "vessels", "history", "alert_settings", "alert_log",
    "windows_notice_log", "permit_documents", "edit_audit",
    "movement_before_state", "movement_edit_audit",
    "movement_deletion_audit", "app_migrations",
)
SCHEMA = (
    """CREATE TABLE IF NOT EXISTS servamar_operational_imports (
        import_id TEXT PRIMARY KEY,
        source_sha256 TEXT NOT NULL UNIQUE,
        source_format TEXT NOT NULL,
        imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        row_counts JSONB NOT NULL,
        document_count INTEGER NOT NULL,
        complete BOOLEAN NOT NULL DEFAULT FALSE
    )""",
    """CREATE TABLE IF NOT EXISTS servamar_operational_rows (
        import_id TEXT NOT NULL REFERENCES servamar_operational_imports(import_id),
        table_name TEXT NOT NULL,
        row_index INTEGER NOT NULL,
        data JSONB NOT NULL,
        PRIMARY KEY(import_id,table_name,row_index)
    )""",
    """CREATE TABLE IF NOT EXISTS servamar_operational_documents (
        import_id TEXT NOT NULL REFERENCES servamar_operational_imports(import_id),
        storage_name TEXT NOT NULL,
        mime TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        content BYTEA NOT NULL,
        PRIMARY KEY(import_id,storage_name)
    )""",
)


def _read_zip(path):
    path = Path(path)
    if not path.is_file():
        raise ValueError("No existe el archivo de respaldo")
    if path.stat().st_size > MAX_TOTAL_BYTES:
        raise ValueError("El archivo excede el límite de seguridad")
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_TOTAL_BYTES:
            raise ValueError("Respaldo demasiado grande")
        names = [i.filename for i in infos]
        if len(names) != len(set(names)):
            raise ValueError("El respaldo contiene nombres duplicados")
        if not {"manifest.json", "embarcaciones.sqlite3"}.issubset(names):
            raise ValueError("Faltan archivos esenciales")
        if any(n not in ("manifest.json", "embarcaciones.sqlite3") and not DOC_NAME.fullmatch(n) for n in names):
            raise ValueError("Ruta inesperada en el respaldo")
        if any(i.is_dir() or i.flag_bits & 1 or i.compress_type not in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED) for i in infos):
            raise ValueError("Archivo comprimido inválido o cifrado")
        manifest = json.loads(z.read("manifest.json"))
        if manifest.get("format") != FORMAT:
            raise ValueError("Formato de respaldo desconocido")
        files = manifest.get("files")
        if not isinstance(files, list) or len(files) != len(names)-1:
            raise ValueError("Manifiesto incompleto")
        expected = {}
        for item in files:
            name = item.get("path")
            if name in expected or name not in names or name == "manifest.json":
                raise ValueError("Manifiesto duplicado o inconsistente")
            blob = z.read(name)
            if len(blob) != item.get("bytes") or hashlib.sha256(blob).hexdigest() != item.get("sha256"):
                raise ValueError("Integridad SHA-256 incorrecta: " + name)
            expected[name] = blob
        if set(expected) != set(names)-{"manifest.json"}:
            raise ValueError("Manifiesto no corresponde a los archivos")
        if manifest.get("missing_documents"):
            raise ValueError("Respaldo incompleto: faltan documentos; no se puede migrar")
    return manifest, expected


def inspect_backup(path):
    manifest, files = _read_zip(path)
    with tempfile.TemporaryDirectory() as temp:
        dbpath = Path(temp)/"source.sqlite3"
        dbpath.write_bytes(files["embarcaciones.sqlite3"])
        with sqlite3.connect(f"file:{dbpath}?mode=ro", uri=True) as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("La base SQLite no supera integrity_check")
            available = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "vessels" not in available or "history" not in available or "permit_documents" not in available:
                raise ValueError("Faltan tablas operativas esenciales")
            counts = {t:db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                      for t in TABLES if t in available}
            docrows = db.execute("SELECT storage_name,sha256,mime FROM permit_documents").fetchall()
            if db.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("Hay referencias de tablas inconsistentes")
        document_names = {"private_permits/"+r[0] for r in docrows}
        if document_names != set(files)-{"embarcaciones.sqlite3"}:
            raise ValueError("Los documentos no coinciden con la base SQLite")
        for name,sha,_ in docrows:
            if hashlib.sha256(files["private_permits/"+name]).hexdigest() != sha:
                raise ValueError("Documento alterado: "+name)
    return {"format":manifest["format"],"sha256":hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            "counts":counts,"documents":len(docrows),"missing_documents":0}


def restore_backup(path, destination):
    """Restores into a NEW directory only; never replaces an existing dataset."""
    report = inspect_backup(path)
    destination = Path(destination)
    if destination.exists():
        raise ValueError("La carpeta destino ya existe; no se sobrescribirá")
    _, files = _read_zip(path)
    destination.parent.mkdir(parents=True,exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".servamar-restore-",dir=destination.parent))
    try:
        for name,blob in files.items():
            target = staging/name
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(blob)
        (staging/"restore_receipt.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
        staging.rename(destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return report


def stage_to_neon(path, database_url):
    """Explicit, append-only import into SEPARATE Neon staging tables."""
    if not database_url:
        raise ValueError("Falta SERVAMAR_OPERATIONAL_STAGING_URL")
    report = inspect_backup(path)
    _, files = _read_zip(path)
    import psycopg
    import_id = "full-"+report["sha256"][:32]
    with tempfile.TemporaryDirectory() as temp:
        source = Path(temp)/"source.sqlite3"
        source.write_bytes(files["embarcaciones.sqlite3"])
        with sqlite3.connect(f"file:{source}?mode=ro",uri=True) as db:
            db.row_factory = sqlite3.Row
            with psycopg.connect(database_url,connect_timeout=15) as target:
                target.execute("SELECT pg_advisory_xact_lock(722026)")
                for ddl in SCHEMA:
                    target.execute(ddl)
                existing = target.execute("SELECT complete FROM servamar_operational_imports WHERE import_id=%s",(import_id,)).fetchone()
                if existing:
                    if not existing[0]:
                        raise ValueError("Existe una importación incompleta; requiere revisión")
                    return {**report,"status":"already_staged","import_id":import_id}
                target.execute("""INSERT INTO servamar_operational_imports
                    (import_id,source_sha256,source_format,row_counts,document_count)
                    VALUES (%s,%s,%s,%s::jsonb,%s)""",
                    (import_id,report["sha256"],FORMAT,json.dumps(report["counts"]),report["documents"]))
                for table in report["counts"]:
                    for idx,row in enumerate(db.execute(f"SELECT * FROM {table} ORDER BY rowid")):
                        data = json.dumps(dict(row),ensure_ascii=False,default=str)
                        target.execute("""INSERT INTO servamar_operational_rows
                            (import_id,table_name,row_index,data) VALUES (%s,%s,%s,%s::jsonb)""",
                            (import_id,table,idx,data))
                for row in db.execute("SELECT storage_name,mime,sha256 FROM permit_documents"):
                    target.execute("""INSERT INTO servamar_operational_documents
                        (import_id,storage_name,mime,sha256,content) VALUES (%s,%s,%s,%s,%s)""",
                        (import_id,row["storage_name"],row["mime"],row["sha256"],
                         files["private_permits/"+row["storage_name"]]))
                actual = dict(target.execute("""SELECT table_name,COUNT(*)::int
                    FROM servamar_operational_rows WHERE import_id=%s GROUP BY table_name""",(import_id,)).fetchall())
                actual = {t:actual.get(t,0) for t in report["counts"]}
                docs = target.execute("SELECT COUNT(*) FROM servamar_operational_documents WHERE import_id=%s",(import_id,)).fetchone()[0]
                if actual != report["counts"] or docs != report["documents"]:
                    raise ValueError("La importación no coincide con los conteos de origen")
                target.execute("UPDATE servamar_operational_imports SET complete=TRUE WHERE import_id=%s",(import_id,))
    return {**report,"status":"staged","import_id":import_id}


def main():
    parser = argparse.ArgumentParser(description="SERVAMAR: verificar, restaurar o preparar una copia operativa")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--verify",action="store_true")
    group.add_argument("--restore-to",metavar="DIRECTORIO")
    group.add_argument("--stage-neon",action="store_true")
    parser.add_argument("backup",help="Archivo servamar_respaldo_completo_*.zip")
    args=parser.parse_args()
    if args.verify: report=inspect_backup(args.backup)
    elif args.restore_to: report=restore_backup(args.backup,args.restore_to)
    else: report=stage_to_neon(args.backup,os.getenv("SERVAMAR_OPERATIONAL_STAGING_URL",""))
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
