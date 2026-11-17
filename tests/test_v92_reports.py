"""V92 read-only search and CSV regression tests."""
import base64
import os
import unittest
from unittest.mock import patch
import postgres_test_app as target

class SearchTests(unittest.TestCase):
    def setUp(self):
        env={'SERVAMAR_PG_TEST_MODE':'YES','SERVAMAR_PG_TEST_PASSWORD':'fictional-test-password-long',
             'SERVAMAR_PG_TEST_USERNAME':'servamar-test','SERVAMAR_PG_TEST_BRANCH_ID':target.TEST_BRANCH,
             'SERVAMAR_PG_TEST_DATABASE_URL':'postgresql://invalid/test','SERVAMAR_PG_TEST_REQUIRE_HTTPS':'YES'}
        self.p=patch.dict(os.environ,env);self.p.start();self.addCleanup(self.p.stop)
        self.client=target.app.test_client()
        auth=base64.b64encode(b'servamar-test:fictional-test-password-long').decode()
        self.headers={'Authorization':'Basic '+auth,'X-Forwarded-Proto':'https'}

    def test_invalid_month_and_long_query(self):
        for query in ('month=2026-13','month=2026-1','month=invalid','q='+('a'*121)):
            self.assertEqual(self.client.get('/api/test/search?'+query,headers=self.headers).status_code,400)
            self.assertEqual(self.client.get('/api/test/export.csv?'+query,headers=self.headers).status_code,400)

    def test_authentication(self):
        for path in ('/api/test/search','/api/test/expiring','/api/test/export.csv'):
            self.assertEqual(self.client.get(path).status_code,401)

    def test_csv_formula_escaping(self):
        import postgres_test_reports as reports
        class Cursor:
            def fetchall(self): return [(1,'ST-TEST-001','=SUM(1,2)','Ficticio','R1','ingreso',None,None)]
        class DB:
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def execute(self,sql,params):
                assert 'LIMIT 1000' in sql
                assert 'ST-(DEMO|TEST)-' in params
                return Cursor()
        with patch.object(target,'connection',return_value=DB()):
            result=self.client.get('/api/test/export.csv',headers=self.headers)
            self.assertEqual(result.status_code,200)
            self.assertIn("'=SUM(1,2)",result.text)
            self.assertIn('attachment',result.headers['Content-Disposition'])
            search=self.client.get('/api/test/search?q=Ficticio',headers=self.headers)
            self.assertEqual(search.status_code,200)
            self.assertEqual(search.json['count'],1)

if __name__=='__main__':unittest.main()
