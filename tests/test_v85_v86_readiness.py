import tempfile,unittest
from pathlib import Path
from operational_cutover_readiness import readiness_report
from operational_backup_retention import retain_verified
from operational_neon_export import create_export
class Cursor:
 def __init__(self,rows):self.rows=rows
 def fetchone(self):return self.rows[0] if self.rows else None
 def fetchall(self):return self.rows
 def __iter__(self):return iter(self.rows)
class DB:
 def execute(self,sql,params=None):
  if "SELECT complete,row_counts,document_count" in sql:return Cursor([(True,{"vessels":1,"history":0,"alert_settings":1},0)])
  if "SELECT row_counts,document_count" in sql:return Cursor([({"vessels":1,"history":0,"alert_settings":1},0)])
  if "FROM servamar_operational_documents" in sql:return Cursor([])
  if "FROM servamar_operational_rows" in sql:
   return Cursor([("alert_settings",0,{"vessel_id":1,"days_before":30,"enabled":1}),("vessels",0,{"id":1,"declaration":"TEST","stage":"ingreso"})])
  raise AssertionError(sql)
class Tests(unittest.TestCase):
 def test_readiness_blocks_unverified_gates(self):
  report=readiness_report(DB(),"test",sqlite_verified=True)
  self.assertFalse(report["ready_for_cutover"])
  self.assertIn("postgres_restore_test",report["blockers"])
  self.assertIn("schema_metadata_complete",report["blockers"])
 def test_verified_copy(self):
  with tempfile.TemporaryDirectory() as d:
   source=Path(d)/"source.zip"
   create_export(DB(),"test",source)
   result=retain_verified(source,Path(d)/"offsite")
   self.assertTrue(result["verified"])
   self.assertTrue(Path(result["saved"]).exists())
   self.assertFalse(result["offsite_verified"])
   self.assertFalse(result["pruning_performed"])
 def test_rejects_low_retention(self):
  with self.assertRaises(ValueError):retain_verified("missing.zip","/tmp",keep=1)
if __name__=="__main__":unittest.main()
