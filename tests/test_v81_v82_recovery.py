import json,sqlite3,tempfile,unittest
from pathlib import Path
from operational_neon_export import create_export,verify_export
from operational_recovery_rehearsal import rehearse
class FakeCursor:
 def __init__(self,rows):self.rows=rows
 def fetchone(self):return self.rows[0] if self.rows else None
 def fetchall(self):return self.rows
 def __iter__(self):return iter(self.rows)
class FakeDB:
 def execute(self,sql,params=None):
  if "FROM servamar_operational_imports" in sql:
   return FakeCursor([(True,{"vessels":1,"history":0,"alert_settings":1},0)])
  if "FROM servamar_operational_documents" in sql:return FakeCursor([])
  if "FROM servamar_operational_rows" in sql:
   return FakeCursor([("alert_settings",0,{"vessel_id":1,"days_before":30,"enabled":1}),
     ("vessels",0,{"id":1,"declaration":"TEST","name":"Ficticia","stage":"ingreso"})])
  raise AssertionError(sql)
class RecoveryTests(unittest.TestCase):
 def test_export_and_restore_roundtrip(self):
  with tempfile.TemporaryDirectory() as d:
   z=Path(d)/"export.zip";out=Path(d)/"rehearsal.sqlite3"
   summary=create_export(FakeDB(),"test-import",z)
   self.assertTrue(summary["valid"])
   result=rehearse(z,out)
   self.assertEqual(result["recovered_rows"],2)
   self.assertFalse(result["production_restored"])
   with sqlite3.connect(out) as db:
    self.assertEqual(db.execute("SELECT COUNT(*) FROM recovered_rows").fetchone()[0],2)
    self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0],"ok")
   with self.assertRaises(FileExistsError):rehearse(z,out)
 def test_corrupt_zip_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   z=Path(d)/"invalid.zip";z.write_bytes(b"not a zip")
   with self.assertRaises(Exception):rehearse(z,Path(d)/"recovered.sqlite3")
if __name__=="__main__":unittest.main()
