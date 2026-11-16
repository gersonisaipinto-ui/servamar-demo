"""V73: read-only validation adapter for imported SQLite operational snapshots.

Never used as an operational database connection. Does not modify the application.
"""
import hashlib
import json
from collections import Counter

EXPECTED_TABLES = (
 "vessels","history","alert_settings","alert_log","windows_notice_log",
 "permit_documents","edit_audit","movement_before_state",
 "movement_edit_audit","movement_deletion_audit","app_migrations",
)

def summarize_rows(rows):
 """Validate staged JSON rows without changing source business rules."""
 vessels = rows.get("vessels", [])
 alerts = rows.get("alert_settings", [])
 history = rows.get("history", [])
 ids = [v.get("id") for v in vessels]
 if len(ids) != len(set(ids)) or any(i is None for i in ids):
  raise ValueError("Identificadores de embarcación duplicados o vacíos")
 vessel_ids = set(ids)
 if any(a.get("vessel_id") not in vessel_ids for a in alerts):
  raise ValueError("Alerta asociada a una embarcación inexistente")
 if any(h.get("vessel_id") not in vessel_ids for h in history):
  raise ValueError("Movimiento asociado a una embarcación inexistente")
 alert_keys = [(a.get("vessel_id"),a.get("days_before")) for a in alerts]
 if len(alert_keys) != len(set(alert_keys)):
  raise ValueError("Configuraciones de alerta duplicadas")
 return {
  "vessels":len(vessels),"history":len(history),
  "alert_settings":len(alerts),
  "alerts_by_vessel":dict(sorted(Counter(str(a["vessel_id"]) for a in alerts).items())),
  "vessel_declarations":sorted(str(v.get("declaration","")) for v in vessels),
 }

def load_staging(connection, import_id):
 """Read an explicitly completed import, never merge with DEMO records."""
 row = connection.execute(
  "SELECT complete,row_counts,document_count FROM servamar_operational_imports WHERE import_id=%s",
  (import_id,)
 ).fetchone()
 if not row or not row[0]:
  raise ValueError("La importación no existe o no está completa")
 counts = row[1] if isinstance(row[1],dict) else json.loads(row[1])
 records = {table:[] for table in counts}
 for table,index,data in connection.execute(
  "SELECT table_name,row_index,data FROM servamar_operational_rows WHERE import_id=%s ORDER BY table_name,row_index",
  (import_id,)
 ):
  if table not in records:raise ValueError("Tabla de importación inesperada")
  if index != len(records[table]):raise ValueError("Secuencia de filas incompleta")
  records[table].append(data if isinstance(data,dict) else json.loads(data))
 for table,expected in counts.items():
  if len(records[table]) != expected:
   raise ValueError("Recuento de filas inconsistente: "+table)
 docs = connection.execute(
  "SELECT storage_name,sha256,content FROM servamar_operational_documents WHERE import_id=%s",
  (import_id,)
 ).fetchall()
 if len(docs) != row[2]:raise ValueError("Recuento de documentos inconsistente")
 for name,sha,content in docs:
  if hashlib.sha256(bytes(content)).hexdigest() != sha:
   raise ValueError("Documento alterado: "+name)
 summary = summarize_rows(records)
 summary["documents"] = len(docs)
 summary["import_id"] = import_id
 return summary

def compare_with_sqlite(sqlite_connection, staging_summary):
 """Compare identities and counts; no mutation, no implicit reconciliation."""
 sqlite_connection.row_factory = __import__("sqlite3").Row
 available = {r[0] for r in sqlite_connection.execute(
  "SELECT name FROM sqlite_master WHERE type='table'")}
 counts = {}
 for table in ("vessels","history","alert_settings"):
  counts[table] = sqlite_connection.execute(
   f"SELECT COUNT(*) FROM {table}").fetchone()[0] if table in available else 0
 names = sorted(r[0] for r in sqlite_connection.execute(
  "SELECT declaration FROM vessels")) if "vessels" in available else []
 match = all(staging_summary[k]==v for k,v in counts.items()) and names==staging_summary["vessel_declarations"]
 return {"match":match,"source_counts":counts,"staging_counts":{k:staging_summary[k] for k in counts},
         "source_declarations":names,"staging_declarations":staging_summary["vessel_declarations"]}
