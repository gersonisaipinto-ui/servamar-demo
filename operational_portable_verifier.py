"""V84: portable export verifier for offline staging recovery rehearsals.

The ZIP is an audit artifact only, not a complete PostgreSQL pg_dump.
"""
import hashlib,json,zipfile
from collections import Counter
from pathlib import Path
from operational_staging_adapter import summarize_rows

def verify_portable_archive(path):
 with zipfile.ZipFile(path) as z:
  names=z.namelist()
  if len(names)!=len(set(names)) or "manifest.json" not in names or "staging.json" not in names:
   raise ValueError("Missing or duplicate archive entries")
  manifest=json.loads(z.read("manifest.json"))
  if manifest.get("format")!="servamar-neon-staging-export-v80":raise ValueError("Unexpected archive format")
  files=manifest.get("files",{})
  if set(names)!=set(files)|{"manifest.json"}:raise ValueError("Unexpected or missing entries")
  for name,meta in files.items():
   if name.startswith("/") or "\\" in name or ".." in name.split("/"):
    raise ValueError("Unsafe ZIP path")
   raw=z.read(name)
   if hashlib.sha256(raw).hexdigest()!=meta["sha256"] or len(raw)!=meta["bytes"]:
    raise ValueError("Checksum mismatch: "+name)
  payload=json.loads(z.read("staging.json"))
  if payload.get("format")!="servamar-neon-staging-v80":raise ValueError("Unexpected staging format")
  rows=payload["rows"]
  grouped={}
  for row in rows:
   grouped.setdefault(row["table"],[]).append(row)
  for table,group in grouped.items():
   indices=sorted(r["index"] for r in group)
   if indices!=list(range(len(group))):raise ValueError("Duplicate or missing row index: "+table)
  summary=payload["summary"]
  for table in ("vessels","history","alert_settings"):
   if len(grouped.get(table,[]))!=summary[table]:
    raise ValueError("Row count mismatch: "+table)
  records={table:[r["data"] for r in group] for table,group in grouped.items()}
  validated=summarize_rows(records)
  for key in ("vessels","history","alert_settings"):
   if validated[key]!=summary[key]:raise ValueError("Semantic count mismatch: "+key)
  documents=[name for name in names if name.startswith("documents/")]
  if len(documents)!=summary["documents"]:raise ValueError("Document count mismatch")
  return {"verified":True,"import_id":payload["import_id"],"rows":len(rows),
          "vessels":validated["vessels"],"alerts":validated["alert_settings"],
          "documents":len(documents),"postgres_restored":False}
