import os,unittest
from unittest.mock import patch
import postgres_test_app as target
class TestPostgresConsole(unittest.TestCase):
 def setUp(self):
  self.env=patch.dict(os.environ,{"SERVAMAR_PG_TEST_MODE":"YES","SERVAMAR_PG_TEST_PASSWORD":"very-long-testing-password","SERVAMAR_PG_TEST_BRANCH_ID":"br-green-band-arsmtoxc","SERVAMAR_PG_TEST_DATABASE_URL":"postgresql://example.invalid/test"})
  self.env.start()
  self.client=target.app.test_client()
 def tearDown(self):self.env.stop()
 def test_requires_auth(self):
  self.assertEqual(self.client.get("/").status_code,401)
 def test_disabled_without_branch_guard(self):
  with patch.dict(os.environ,{"SERVAMAR_PG_TEST_BRANCH_ID":"other"}):
   self.assertEqual(self.client.get("/").status_code,503)
 def test_health_does_not_expose_password(self):
  self.assertNotIn("very-long-testing-password",self.client.get("/healthz").get_data(as_text=True))
 def test_rejects_real_declarations(self):
  with self.assertRaises(ValueError):target.ensure_test_declaration("REAL-001")
 def test_allows_fictional_declarations(self):
  target.ensure_test_declaration("ST-TEST-004")
 def test_rejects_invalid_date(self):
  with self.assertRaises(ValueError):target.parse_date("31/11/2026")
if __name__=="__main__":unittest.main()
