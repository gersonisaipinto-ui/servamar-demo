"""V88: independent, read-only SQL checks for a future PostgreSQL restore.

Checks exact staging rows and foreign-key-like references without altering data.
This is NOT a full PostgreSQL restore.
"""
from operational_staging_adapter import load_staging

def inspect_restore_candidate(connection,import_id):
 summary=load_staging(connection,import_id)
 rows=connection.execute("SELECT table_name,row_index,data FROM servamar_operational_rows WHERE import_id=%s ORDER BY table_name,row_index",(import_id,)).fetchall()
 ids=set();duplicates=[];orphans=[]
 import json
 parsed=[(table,index,data if isinstance(data,dict) else json.loads(data)) for table,index,data in rows]
 for table,index,data in parsed:
  if table=="vessels":
   if data.get("id") in ids:duplicates.append(data.get("id"))
   ids.add(data.get("id"))
 for table,index,data in parsed:
  if table in ("history","alert_settings") and data.get("vessel_id") not in ids:
   orphans.append({"table":table,"row_index":index})
 return {"import_id":import_id,"vessels":len(ids),"history":summary["history"],
         "alerts":summary["alert_settings"],"duplicate_vessel_ids":duplicates,
         "orphan_rows":orphans,"internally_consistent":not duplicates and not orphans,
         "postgres_restore_performed":False,"production_cutover_performed":False}
