import unittest
from operational_safe_projection import safe_projection
from operational_restore_inspector import inspect_restore_candidate
class Cursor:
 def __init__(self,rows):self.rows=rows
 def fetchone(self):return self.rows[0] if self.rows else None
 def fetchall(self):return self.rows
 def __iter__(self):return iter(self.rows)
class DB:
 def execute(self,sql,params=None):
  if "SELECT complete,row_counts,document_count" in sql:return Cursor([(True,{"vessels":1,"history":0,"alert_settings":1},0)])
  if "FROM servamar_operational_documents" in sql:return Cursor([])
  if "FROM servamar_operational_rows" in sql:return Cursor([("alert_settings",0,{"vessel_id":1,"days_before":30}),("vessels",0,{"id":1,"declaration":"TEST"})])
  raise AssertionError(sql)
class Tests(unittest.TestCase):
 def test_no_double_count_without_provenance(self):
  v={"stage":"ingreso","start_date":"2026-11-04","expiry_date":"2027-02-12"}
  m=[{"kind":"salida","event_date":"2026-11-10"},{"kind":"retorno","event_date":"2026-11-20"}]
  r=safe_projection(v,m,"2026-11-21")
  self.assertEqual(r["expiry_date"],"2027-02-12")
  self.assertTrue(r["needs_review"])
 def test_explicit_excludes_return_days(self):
  v={"stage":"ingreso","start_date":"2026-11-04","expiry_date":"2027-02-02"}
  m=[{"kind":"salida","event_date":"2026-11-10"},{"kind":"retorno","event_date":"2026-11-20"}]
  self.assertEqual(safe_projection(v,m,"2026-11-21","excludes_return_days")["expiry_date"],"2027-02-12")
 def test_extension_anniversary_discrepancy(self):
  r=safe_projection({"stage":"ampliacion","start_date":"2026-11-04","expiry_date":"2027-11-04"},[],"2026-11-21")
  self.assertTrue(r["needs_review"])
 def test_inspector(self):
  r=inspect_restore_candidate(DB(),"test")
  self.assertTrue(r["internally_consistent"])
  self.assertFalse(r["postgres_restore_performed"])
if __name__=="__main__":unittest.main()
