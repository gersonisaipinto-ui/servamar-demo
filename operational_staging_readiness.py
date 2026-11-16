"""V83: read-only validation of Neon staging export/recovery prerequisites.

Fail closed: staging must match import metadata and all original table
families must be accounted for. No database writes or operational cutover.
"""
import hashlib,json
from collections import Counter
from operational_staging_adapter import load_staging,EXPECTED_TABLES

def inspect_staging(connection,import_id):
 summary=load_staging(connection,import_id)
 meta=connection.execute("SELECT row_counts,document_count FROM servamar_operational_imports WHERE import_id=%s",(import_id,)).fetchone()
 if not meta:raise ValueError("Import not found")
 counts=meta[0] if isinstance(meta[0],dict) else json.loads(meta[0])
 if set(counts)-set(EXPECTED_TABLES):
  raise ValueError("Unexpected source table in import metadata")
 records=connection.execute("SELECT table_name,row_index,data FROM servamar_operational_rows WHERE import_id=%s ORDER BY table_name,row_index",(import_id,)).fetchall()
 grouped={}
 for table,index,data in records:
  grouped.setdefault(table,[]).append((index,data if isinstance(data,dict) else json.loads(data)))
 if set(grouped)-set(counts):raise ValueError("Unexpected staged table")
 for table,expected in counts.items():
  rows=grouped.get(table,[])
  if len(rows)!=expected or sorted(index for index,_ in rows)!=list(range(expected)):
   raise ValueError("Staging row count or sequence mismatch: "+table)
 missing=sorted(set(EXPECTED_TABLES)-set(counts))
 # Metadata may predate later schema migrations. This is an audit caveat,
 # not permission to invent or drop tables.
 return {"import_id":import_id,"rows":sum(counts.values()),
         "vessels":summary["vessels"],"history":summary["history"],
         "alerts":summary["alert_settings"],"documents":summary["documents"],
         "missing_table_metadata":missing,
         "ready_for_production_cutover":False,
         "reason":"Full operational restore, historical parity and external backup policy not verified"}
