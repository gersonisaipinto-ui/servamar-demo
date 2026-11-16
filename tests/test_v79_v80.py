import json,tempfile,unittest,zipfile
from pathlib import Path
from operational_legacy_parity import compare_scenario
from operational_neon_export import verify_export
class V79V80Tests(unittest.TestCase):
 def vessel(self):return {"stage":"ingreso","start_date":"2026-11-04","expiry_date":"2027-02-02"}
 def test_manual_return_parity(self):
  result=compare_scenario(self.vessel(),[{"kind":"salida","event_date":"2026-11-10"},{"kind":"retorno","event_date":"2026-11-20"}],"2026-11-21")
  self.assertEqual(result["differences"],[])
  self.assertTrue(result["ready_for_cutover"])
 def test_open_exit_parity(self):
  result=compare_scenario(self.vessel(),[{"kind":"salida","event_date":"2026-11-10"}],"2026-11-20")
  self.assertEqual(result["differences"],[])
 def test_historical_return_requires_review(self):
  result=compare_scenario(self.vessel(),[{"kind":"salida_archivo","event_date":"2026-11-10"},{"kind":"retorno_archivo","event_date":"2026-11-20"}],"2026-11-21")
  self.assertTrue(result["historical_review_required"])
  self.assertFalse(result["ready_for_cutover"])
 def test_ninety_day_closure(self):
  result=compare_scenario(self.vessel(),[{"kind":"salida","event_date":"2026-11-10"}],"2027-02-08")
  self.assertEqual(result["differences"],[])
  self.assertTrue(result["legacy"]["must_close"])
 def test_export_rejects_bad_checksum(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/"bad.zip"
   with zipfile.ZipFile(p,"w") as z:
    z.writestr("manifest.json",json.dumps({"format":"servamar-neon-staging-export-v80","files":{"staging.json":{"bytes":3,"sha256":"bad"}}}))
    z.writestr("staging.json","bad")
   with self.assertRaisesRegex(ValueError,"integrity"):
    verify_export(p)
 def test_export_rejects_missing_files(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/"missing.zip"
   with zipfile.ZipFile(p,"w") as z:
    z.writestr("manifest.json",json.dumps({"format":"servamar-neon-staging-export-v80","files":{"staging.json":{"bytes":3,"sha256":"bad"}}}))
   with self.assertRaisesRegex(ValueError,"Missing"):
    verify_export(p)
if __name__=="__main__":unittest.main()
