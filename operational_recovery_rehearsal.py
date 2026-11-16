"""V81: offline recovery rehearsal of a V80 staging ZIP into a NEW SQLite file.

Does not modify PostgreSQL or the SERVAMAR operational database. The result
is an audit copy of the exported JSON rows, not a drop-in SERVAMAR database.
"""
import argparse,hashlib,json,sqlite3,tempfile
from pathlib import Path
from zipfile import ZipFile
from operational_neon_export import verify_export
from operational_staging_adapter import summarize_rows

def rehearse(zip_path,target):
 verification=verify_export(zip_path)
 with ZipFile(zip_path) as archive:
  payload=json.loads(archive.read("staging.json"))
 rows=payload["rows"]
 table_counts=payload["summary"]
 records={}
 for row in rows:
  table=row["table"]
  records.setdefault(table,[]).append(row["data"])
  if not isinstance(row["index"],int) or row["index"]<0:
   raise ValueError("Invalid row index")
 for table in ("vessels","history","alert_settings"):
  if len(records.get(table,[]))!=table_counts[table]:
   raise ValueError("Source row count mismatch: "+table)
 summarize_rows(records)
 for table in set(r["table"] for r in rows):
  indices=sorted(r["index"] for r in rows if r["table"]==table)
  if indices!=list(range(len(indices))):
   raise ValueError("Missing or duplicate row sequence: "+table)
 target=Path(target)
 if target.exists():raise FileExistsError("Refusing to overwrite an existing database")
 target.parent.mkdir(parents=True,exist_ok=True)
 # Create temporary file in the same directory for atomic rename.
 with tempfile.NamedTemporaryFile(dir=target.parent,suffix=".sqlite3",delete=False) as tmp:
  temp_path=Path(tmp.name)
 try:
  with sqlite3.connect(temp_path) as db:
   db.execute("CREATE TABLE recovered_rows (table_name TEXT NOT NULL,row_index INTEGER NOT NULL,data_json TEXT NOT NULL,PRIMARY KEY(table_name,row_index))")
   db.execute("CREATE TABLE recovered_meta (import_id TEXT NOT NULL,format TEXT NOT NULL)")
   db.execute("INSERT INTO recovered_meta VALUES (?,?)",(verification["import_id"],"servamar-recovery-rehearsal-v81"))
   db.executemany("INSERT INTO recovered_rows VALUES (?,?,?)",[(r["table"],r["index"],json.dumps(r["data"],sort_keys=True,ensure_ascii=False)) for r in rows])
   if db.execute("PRAGMA integrity_check").fetchone()[0]!="ok":raise ValueError("Recovery SQLite failed integrity check")
   actual=db.execute("SELECT COUNT(*) FROM recovered_rows").fetchone()[0]
   if actual!=len(rows):raise ValueError("Recovered row count mismatch")
  temp_path.replace(target)
 except BaseException:
  temp_path.unlink(missing_ok=True)
  raise
 return {"verified":True,"recovered_rows":len(rows),"import_id":verification["import_id"],
         "output":str(target),"production_restored":False}
def main():
 parser=argparse.ArgumentParser()
 parser.add_argument("backup_zip")
 parser.add_argument("recovery_sqlite")
 args=parser.parse_args()
 print(json.dumps(rehearse(args.backup_zip,args.recovery_sqlite),ensure_ascii=False))
if __name__=="__main__":main()
