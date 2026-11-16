import unittest
from operational_parity_report import compare
class ReportTests(unittest.TestCase):
 def test_identical(self):
  a={'vessels':[{'id':1,'name':'A'}]}
  self.assertTrue(compare(a,a)['rows_identical'])
  self.assertFalse(compare(a,a)['ready_for_cutover'])
 def test_changed_vessel_field(self):
  a={'vessels':[{'id':1,'name':'A'}]};b={'vessels':[{'id':1,'name':'B'}]}
  result=compare(a,b)
  self.assertFalse(result['rows_identical'])
  self.assertEqual(result['vessels'][0]['different_fields'],['name'])
 def test_missing_alert(self):
  a={'alert_settings':[{'vessel_id':1,'days_before':30}]}
  self.assertFalse(compare(a,{})['rows_identical'])
 def test_order_independent(self):
  a={'history':[{'id':2},{'id':1}]};b={'history':[{'id':1},{'id':2}]}
  self.assertTrue(compare(a,b)['rows_identical'])
if __name__=='__main__':unittest.main()
