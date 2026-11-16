import unittest
from datetime import date
from operational_pg_sandbox import validate_vessel,validate_movement,SCHEMA

class V74Tests(unittest.TestCase):
 def test_valid_vessel(self):
  x=validate_vessel({"declaration":" TEST ","name":" BARCO ","start_date":"2026-11-16","expiry_date":"2027-02-14"})
  self.assertEqual(x["name"],"BARCO")
  self.assertEqual(x["start_date"],date(2026,11,16))
 def test_reject_missing_identity(self):
  with self.assertRaises(ValueError):validate_vessel({"name":"X"})
 def test_reject_expiry_before_entry(self):
  with self.assertRaises(ValueError):validate_vessel({"name":"X","declaration":"Y","start_date":"2026-11-16","expiry_date":"2026-11-15"})
 def test_reject_unknown_stage(self):
  with self.assertRaises(ValueError):validate_vessel({"name":"X","declaration":"Y","stage":"unknown"})
 def test_movement(self):
  self.assertEqual(validate_movement({"kind":"salida_temporal","event_date":"2026-11-16"})["kind"],"salida_temporal")
 def test_reject_unknown_movement(self):
  with self.assertRaises(ValueError):validate_movement({"kind":"inventado","event_date":"2026-11-16"})
 def test_reject_missing_movement_date(self):
  with self.assertRaises(ValueError):validate_movement({"kind":"ingreso"})
 def test_reject_invalid_movement_dates(self):
  with self.assertRaises(ValueError):validate_movement({"kind":"ingreso","event_date":"2026-11-16","expiry_date":"2026-11-01"})
 def test_schema_is_separate_and_referenced(self):
  self.assertEqual(len(SCHEMA),4)
  self.assertTrue(all("v74_sandbox_" in s for s in SCHEMA))
  self.assertTrue(any("REFERENCES v74_sandbox_vessels" in s for s in SCHEMA))
if __name__=="__main__":unittest.main()
