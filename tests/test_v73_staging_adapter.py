import sqlite3
import unittest
from operational_staging_adapter import summarize_rows,compare_with_sqlite,load_staging

class AdapterTests(unittest.TestCase):
 def setUp(self):
  self.rows={"vessels":[{"id":1,"declaration":"ST-DEMO-001"}],
             "alert_settings":[{"vessel_id":1,"days_before":30}],
             "history":[]}
 def test_summary(self):
  s=summarize_rows(self.rows)
  self.assertEqual((s["vessels"],s["alert_settings"],s["history"]),(1,1,0))
 def test_rejects_orphan_alert(self):
  self.rows["alert_settings"][0]["vessel_id"]=9
  with self.assertRaisesRegex(ValueError,"inexistente"):
   summarize_rows(self.rows)
 def test_rejects_duplicate_vessels(self):
  self.rows["vessels"].append(dict(self.rows["vessels"][0]))
  with self.assertRaisesRegex(ValueError,"duplicados"):
   summarize_rows(self.rows)
 def test_rejects_duplicate_alerts(self):
  self.rows["alert_settings"].append(dict(self.rows["alert_settings"][0]))
  with self.assertRaisesRegex(ValueError,"duplicadas"):
   summarize_rows(self.rows)
 def test_compare_source(self):
  db=sqlite3.connect(":memory:")
  db.execute("CREATE TABLE vessels(id INTEGER,declaration TEXT)")
  db.execute("CREATE TABLE history(id INTEGER)")
  db.execute("CREATE TABLE alert_settings(vessel_id INTEGER,days_before INTEGER)")
  db.execute("INSERT INTO vessels VALUES(1,'ST-DEMO-001')")
  db.execute("INSERT INTO alert_settings VALUES(1,30)")
  self.assertTrue(compare_with_sqlite(db,summarize_rows(self.rows))["match"])
  db.execute("INSERT INTO history VALUES(1)")
  self.assertFalse(compare_with_sqlite(db,summarize_rows(self.rows))["match"])
 def test_incomplete_import_is_blocked(self):
  class Fake:
   def execute(self,*args):return self
   def fetchone(self):return (False,{},0)
  with self.assertRaisesRegex(ValueError,"no está completa"):
   load_staging(Fake(),"any")
if __name__=="__main__":unittest.main()
