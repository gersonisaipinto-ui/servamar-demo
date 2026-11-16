import hashlib
import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from operational_backup import inspect_backup,restore_backup,stage_to_neon

class OperationalBackupTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory()
  self.addCleanup(self.temp.cleanup)
  self.root=Path(self.temp.name)
  self.db=self.root/"embarcaciones.sqlite3"
  with sqlite3.connect(self.db) as c:
   c.execute("PRAGMA foreign_keys=ON")
   c.execute("CREATE TABLE vessels(id INTEGER PRIMARY KEY,name TEXT)")
   c.execute("CREATE TABLE history(id INTEGER PRIMARY KEY,vessel_id INTEGER REFERENCES vessels(id),kind TEXT)")
   c.execute("CREATE TABLE permit_documents(id INTEGER PRIMARY KEY,vessel_id INTEGER REFERENCES vessels(id),storage_name TEXT,mime TEXT,sha256 TEXT)")
   c.execute("INSERT INTO vessels VALUES(7,'EMBARCACION FICTICIA')")
   c.execute("INSERT INTO history VALUES(2,7,'ingreso')")
  self.document="a"*32+".pdf"
  self.content=b"%PDF-1.4\nFAKE-TEST-ONLY"
  self.add_document=True
  self.write_backup()

 def write_backup(self,missing=False,tamper=False):
  with sqlite3.connect(self.db) as c:
   c.execute("DELETE FROM permit_documents")
   c.execute("INSERT INTO permit_documents VALUES(1,7,?,?,?)",
      (self.document,"application/pdf",hashlib.sha256(self.content).hexdigest()))
  files={"embarcaciones.sqlite3":self.db.read_bytes()}
  if not missing:files["private_permits/"+self.document]=self.content+(b"CHANGED" if tamper else b"")
  manifest={"format":"servamar-full-backup-v1","files":[
      {"path":n,"bytes":len(b),"sha256":hashlib.sha256(b).hexdigest()} for n,b in files.items()],
      "missing_documents":[self.document] if missing else []}
  self.zip=self.root/"backup.zip"
  with zipfile.ZipFile(self.zip,"w") as z:
   for n,b in files.items():z.writestr(n,b)
   z.writestr("manifest.json",json.dumps(manifest))

 def test_verify_and_restore_to_new_folder(self):
  report=inspect_backup(self.zip)
  self.assertEqual(report["counts"]["vessels"],1)
  self.assertEqual(report["counts"]["history"],1)
  self.assertEqual(report["documents"],1)
  restored=self.root/"restored"
  restore_backup(self.zip,restored)
  self.assertEqual((restored/"private_permits"/self.document).read_bytes(),self.content)
  with sqlite3.connect(restored/"embarcaciones.sqlite3") as db:
   self.assertEqual(db.execute("SELECT name FROM vessels").fetchone()[0],"EMBARCACION FICTICIA")
  with self.assertRaisesRegex(ValueError,"ya existe"):
   restore_backup(self.zip,restored)

 def test_rejects_missing_documents(self):
  self.write_backup(missing=True)
  with self.assertRaisesRegex(ValueError,"faltan documentos"):
   inspect_backup(self.zip)

 def test_rejects_document_content_mismatch(self):
  self.write_backup(tamper=True)
  with self.assertRaisesRegex(ValueError,"Documento alterado"):
   inspect_backup(self.zip)

 def test_rejects_bad_manifest_hash(self):
  with zipfile.ZipFile(self.zip,"a") as z:
   z.writestr("unexpected.txt","NO")
  with self.assertRaises(ValueError):
   inspect_backup(self.zip)

 def test_neon_requires_explicit_connection(self):
  with self.assertRaisesRegex(ValueError,"Falta SERVAMAR_OPERATIONAL_STAGING_URL"):
   stage_to_neon(self.zip,"")

if __name__=="__main__":
 unittest.main()
