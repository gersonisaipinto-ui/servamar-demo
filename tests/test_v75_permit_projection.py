import unittest
from datetime import date
from operational_pg_projection import initial_expiry,extended_expiry,deposit_expiry,project_permit

class PermitProjectionTests(unittest.TestCase):
 def vessel(self,stage="ingreso",start="2026-11-04",expiry=None):
  return {"stage":stage,"start_date":start,"expiry_date":expiry}
 def test_initial_90_days(self):
  self.assertEqual(initial_expiry("2026-11-04"),date(2027,2,2))
 def test_extension_nine_months_after_initial(self):
  self.assertEqual(extended_expiry("2026-11-04"),date(2027,11,2))
 def test_deposit_twelve_months(self):
  self.assertEqual(deposit_expiry("2026-11-04"),date(2027,11,4))
 def test_deposit_end_of_month(self):
  self.assertEqual(deposit_expiry("2024-02-29"),date(2025,2,28))
 def test_exit_return_adds_days(self):
  result=project_permit(self.vessel(),[
   {"kind":"salida","event_date":"2026-11-10"},
   {"kind":"retorno","event_date":"2026-11-20"}],today="2026-11-21")
  self.assertEqual(result["days_added"],10)
  self.assertEqual(result["expiry_date"],"2027-02-12")
 def test_open_exit_under_90(self):
  result=project_permit(self.vessel(),[{"kind":"salida","event_date":"2026-11-10"}],today="2026-11-20")
  self.assertEqual(result["stage"],"salida_temporal")
  self.assertEqual(result["operational_date"],"2027-02-08")
  self.assertEqual(result["days_added"],0)
 def test_open_exit_90_days(self):
  result=project_permit(self.vessel(),[{"kind":"salida","event_date":"2026-11-10"}],today="2027-02-08")
  self.assertEqual(result["stage"],"cierre")
 def test_late_return_does_not_extend(self):
  result=project_permit(self.vessel(),[{"kind":"salida","event_date":"2026-11-10"},{"kind":"retorno","event_date":"2027-02-08"}],today="2027-02-09")
  self.assertEqual(result["stage"],"cierre")
  self.assertEqual(result["days_added"],0)
 def test_deposit_exit_warns(self):
  result=project_permit(self.vessel("deposito"),[{"kind":"salida","event_date":"2026-11-10"}],today="2026-11-20")
  self.assertTrue(any("depósito" in w for w in result["warnings"]))
 def test_recorded_date_is_preserved(self):
  result=project_permit(self.vessel(expiry="2027-03-01"),[],today="2026-11-20")
  self.assertEqual(result["expiry_date"],"2027-03-01")
  self.assertTrue(result["warnings"])
 def test_no_implicit_approval(self):
  result=project_permit(self.vessel(expiry=None),[],today="2026-11-20")
  self.assertTrue(any("sin documento" in w for w in result["warnings"]))
 def test_orphan_return_warns(self):
  result=project_permit(self.vessel(),[{"kind":"retorno","event_date":"2026-11-20"}],today="2026-11-20")
  self.assertTrue(result["warnings"])
if __name__=="__main__":unittest.main()
