import tempfile,unittest
from pathlib import Path
from operational_neon_export import create_export
from operational_portable_verifier import verify_portable_archive
from operational_staging_readiness import inspect_staging
class FakeDB:
 def execute(self,sql,params=None):
  if "SELECT complete,row_counts,document_count" in sql:return Cursor([(True,{"vessels":1,"history":0,"alert_settings":1},0)])
  if "SELECT row_counts,document_count" in sql:return Cursor([({"vessels":1,"history":0,"alert_settings":1},0)])
  if "FROM servamar_operational_documents" in sql:return Cursor([])
  if "FROM servamar_operational_rows" in sql:
   return Cursor([("alert_settings",0,{"vessel_id":1,"days_before":30,"enabled":1}),("vessels",0,{"id":1,"declaration":"TEST","stage":"ingreso"})])
  raise AssertionError(sql)
class Cursor:
 def __init__(self,rows):self.rows=rows
 def fetchone(self):return self.rows[0] if self.rows else None
 def fetchall(self):return self.rows
 def __iter__(self):return iter(self.rows)
class Tests(unittest.TestCase):
 def test_staging_metadata(self):
  r=inspect_staging(FakeDB(),"test")
  self.assertEqual(r["rows"],2)
  self.assertFalse(r["ready_for_production_cutover"])
 def test_portable_roundtrip(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/"staging.zip"
   create_export(FakeDB(),"test",path)
   r=verify_portable_archive(path)
   self.assertEqual(r["rows"],2)
   self.assertFalse(r["postgres_restored"])
 def test_rejects_non_zip(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/"bad.zip";path.write_bytes(b"bad")
   with self.assertRaises(Exception):verify_portable_archive(path)
if __name__=="__main__":unittest.main()
