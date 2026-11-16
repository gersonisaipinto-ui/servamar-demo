"""V80: offline verifiable PostgreSQL staging export (not automatic backups).

Read-only Neon staging export. Contains personal data if source does:
keep ZIP private. Never writes to Neon or replaces production backups.
"""
import argparse,hashlib,io,json,zipfile
from datetime import datetime,timezone
from pathlib import Path
from operational_staging_adapter import load_staging

def create_export(connection,import_id,target):
 summary=load_staging(connection,import_id)
 rows=connection.execute("""SELECT table_name,row_index,data
  FROM servamar_operational_rows WHERE import_id=%s
  ORDER BY table_name,row_index""",(import_id,)).fetchall()
 docs=connection.execute("""SELECT storage_name,sha256,content
  FROM servamar_operational_documents WHERE import_id=%s ORDER BY storage_name""",(import_id,)).fetchall()
 payload={"format":"servamar-neon-staging-v80","import_id":import_id,"summary":summary,
          "rows":[{"table":t,"index":i,"data":d if isinstance(d,dict) else json.loads(d)} for t,i,d in rows]}
 files={"staging.json":json.dumps(payload,sort_keys=True,ensure_ascii=False,default=str).encode("utf-8")}
 for i,(name,sha,content) in enumerate(docs):
  raw=bytes(content)
  if hashlib.sha256(raw).hexdigest()!=sha:raise ValueError("Document hash mismatch")
  files[f"documents/{i:06d}.bin"]=raw
 manifest={"format":"servamar-neon-staging-export-v80","created_at":datetime.now(timezone.utc).isoformat(),
           "files":{name:{"sha256":hashlib.sha256(blob).hexdigest(),"bytes":len(blob)} for name,blob in files.items()}}
 with zipfile.ZipFile(target,"w",compression=zipfile.ZIP_DEFLATED) as z:
  for name,blob in files.items():z.writestr(name,blob)
  z.writestr("manifest.json",json.dumps(manifest,sort_keys=True,indent=2))
 return verify_export(target)
def verify_export(path):
 with zipfile.ZipFile(path) as z:
  names=z.namelist()
  if len(names)!=len(set(names)) or "manifest.json" not in names:
   raise ValueError("Invalid archive entries")
  manifest=json.loads(z.read("manifest.json"))
  if manifest.get("format")!="servamar-neon-staging-export-v80":raise ValueError("Unknown format")
  expected=manifest["files"]
  if set(names)!=(set(expected)|{"manifest.json"}):raise ValueError("Missing or extra file")
  for name,meta in expected.items():
   if name.startswith("/") or ".." in name.split("/") or "\\" in name:raise ValueError("Unsafe archive path")
   blob=z.read(name)
   if len(blob)!=meta["bytes"] or hashlib.sha256(blob).hexdigest()!=meta["sha256"]:
    raise ValueError("Archive integrity failure: "+name)
  payload=json.loads(z.read("staging.json"))
  if payload.get("format")!="servamar-neon-staging-v80":raise ValueError("Invalid payload")
  counts=payload["summary"]
  rows=payload["rows"]
  for table in ("vessels","history","alert_settings"):
   if sum(r["table"]==table for r in rows)!=counts[table]:
    raise ValueError("Staging row count mismatch: "+table)
  if len([x for x in names if x.startswith("documents/")])!=counts["documents"]:
   raise ValueError("Document count mismatch")
  return {"valid":True,"import_id":payload["import_id"],
          "vessels":counts["vessels"],"history":counts["history"],
          "alert_settings":counts["alert_settings"],"documents":counts["documents"]}
def main():
 parser=argparse.ArgumentParser()
 parser.add_argument("--verify",help="Check a previously exported ZIP")
 parser.add_argument("--export",help="Destination ZIP")
 parser.add_argument("--import-id")
 args=parser.parse_args()
 if args.verify:
  print(json.dumps(verify_export(args.verify),ensure_ascii=False));return
 if not args.export or not args.import_id:parser.error("Specify --verify OR --export and --import-id")
 try:import psycopg
 except ImportError:parser.error("Install psycopg[binary] to export")
 import os
 url=os.environ.get("SERVAMAR_OPERATIONAL_STAGING_URL")
 if not url:parser.error("SERVAMAR_OPERATIONAL_STAGING_URL is required")
 target=Path(args.export)
 if target.exists():parser.error("Refusing to overwrite existing backup")
 with psycopg.connect(url) as conn:
  with conn.transaction():
   conn.execute("SET TRANSACTION READ ONLY")
   result=create_export(conn,args.import_id,target)
 print(json.dumps(result,ensure_ascii=False))
if __name__=="__main__":main()
