import unittest
from operational_pg_parity_gate import assess_case,audit_batch
class V76ParityTests(unittest.TestCase):
 def vessel(self,stage="ingreso",expiry="2027-02-02"):
  return {"stage":stage,"start_date":"2026-11-04","expiry_date":expiry}
 def test_clean_case(self):
  self.assertEqual(assess_case(self.vessel(),[],today="2026-11-16")["decision"],"PASS")
 def test_historical_exit_requires_review(self):
  x=assess_case(self.vessel(),[{"kind":"salida_archivo","event_date":"2026-11-08"}],today="2026-11-16")
  self.assertEqual(x["decision"],"REVIEW")
  self.assertEqual(x["projection"]["days_added"],0)
 def test_historical_return_not_credited(self):
  x=assess_case(self.vessel(),[{"kind":"salida_archivo","event_date":"2026-11-08"},{"kind":"retorno_archivo","event_date":"2026-11-10"}],today="2026-11-16")
  self.assertEqual(x["projection"]["days_added"],0)
  self.assertEqual(x["decision"],"REVIEW")
 def test_missing_historical_date_requires_review(self):
  x=assess_case(self.vessel(),[{"kind":"salida_archivo","event_date":None}],today="2026-11-16")
  self.assertEqual(x["decision"],"REVIEW")
 def test_recorded_expiry_not_replaced(self):
  x=assess_case(self.vessel(expiry="2027-04-01"),[],today="2026-11-16")
  self.assertEqual(x["projection"]["expiry_date"],"2027-04-01")
  self.assertEqual(x["decision"],"REVIEW")
 def test_legacy_disagreement_blocks_cutover(self):
  x=audit_batch([{"vessel":self.vessel(),"legacy":{"expiry_date":"2027-02-03"}}],today="2026-11-16")
  self.assertFalse(x["ready_for_cutover"])
  self.assertEqual(x["counts"]["REVIEW"],1)
 def test_unknown_stage_requires_review(self):
  self.assertEqual(assess_case(self.vessel(stage="revision"),[],today="2026-11-16")["decision"],"REVIEW")
 def test_invalid_date_blocks(self):
  x=assess_case({"stage":"ingreso","start_date":"bad-date"},[],today="2026-11-16")
  self.assertEqual(x["decision"],"BLOCK")
 def test_empty_batch_not_ready(self):
  self.assertFalse(audit_batch([])["ready_for_cutover"])
 def test_clean_batch(self):
  x=audit_batch([{"vessel":self.vessel(),"legacy":{"expiry_date":"2027-02-02","stage":"ingreso","days_added":0}}],today="2026-11-16")
  self.assertTrue(x["ready_for_cutover"])
 def test_deposit_exit_review(self):
  x=assess_case(self.vessel(stage="deposito",expiry="2027-11-04"),[{"kind":"salida","event_date":"2026-11-08"}],today="2026-11-16")
  self.assertEqual(x["decision"],"REVIEW")
if __name__=="__main__":unittest.main()
