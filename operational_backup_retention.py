"""V86: safe offline backup rotation with independent verification.

Does not schedule or upload anything. Invoke from a trusted host after
creating a verified export. Never keep the only backup on the app host.
"""
import argparse,hashlib,json,shutil
from pathlib import Path
from datetime import datetime,timezone
from operational_portable_verifier import verify_portable_archive

def retain_verified(source,destination_folder,keep=7):
 if keep<2:raise ValueError("Keep at least two backups")
 source=Path(source)
 verification=verify_portable_archive(source)
 target_dir=Path(destination_folder)
 target_dir.mkdir(parents=True,exist_ok=True)
 digest=hashlib.sha256(source.read_bytes()).hexdigest()
 name=f"servamar-staging-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{digest[:12]}.zip"
 destination=target_dir/name
 if destination.exists():raise FileExistsError("Backup already exists")
 # Copy to temporary file and verify before publication.
 tmp=target_dir/(name+".partial")
 try:
  with source.open("rb") as inp,tmp.open("xb") as out:
   shutil.copyfileobj(inp,out)
  if hashlib.sha256(tmp.read_bytes()).hexdigest()!=digest:raise ValueError("Copy checksum mismatch")
  verify_portable_archive(tmp)
  tmp.replace(destination)
 finally:
  tmp.unlink(missing_ok=True)
 # Never auto-delete archives: manual retention after independent verification.
 return {"saved":str(destination),"sha256":digest,"verified":True,
         "import_id":verification["import_id"],"retention_requested":keep,
         "pruning_performed":False,"offsite_verified":False}
def main():
 p=argparse.ArgumentParser()
 p.add_argument("source_zip");p.add_argument("destination_directory")
 p.add_argument("--keep",type=int,default=7)
 a=p.parse_args()
 print(json.dumps(retain_verified(a.source_zip,a.destination_directory,a.keep),ensure_ascii=False))
if __name__=="__main__":main()
