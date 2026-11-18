"""Unit and real PostgreSQL integration tests; fixtures use an isolated schema."""
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date
import os
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
import uuid

import postgres_test_app as target

PASSWORD = 'fictitious-unit-test-password'
ENV = {'SERVAMAR_PG_TEST_MODE': 'YES', 'SERVAMAR_PG_TEST_PASSWORD': PASSWORD,
       'SERVAMAR_PG_TEST_USERNAME': 'servamar-test', 'SERVAMAR_PG_TEST_BRANCH_ID': target.TEST_BRANCH,
       'SERVAMAR_PG_TEST_DATABASE_URL': 'postgresql://invalid/test', 'SERVAMAR_PG_TEST_REQUIRE_HTTPS': 'YES'}


class ConsoleTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, ENV)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client = target.app.test_client()
        self.headers = {'Authorization': 'Basic ' + base64.b64encode(('servamar-test:' + PASSWORD).encode()).decode(),
                        'X-Forwarded-Proto': 'https', 'X-CSRF-Token': target.csrf_token()}

    def request(self, method, path, data=None):
        return self.client.open(path, method=method, json=data, headers=self.headers)

    def test_date_formats_and_leap_year(self):
        for value in ('17/11/2026', '2026-11-17'):
            self.assertEqual(target.parse_date(value), date(2026, 11, 17))
        self.assertEqual(target.parse_date('29/02/2024'), date(2024, 2, 29))
        self.assertIsNone(target.parse_date(''))
        for value in ('29/02/2025', '31/11/2026', '1/2/2026', '20261117', [], 123):
            with self.subTest(value=value), self.assertRaises(ValueError):
                target.parse_date(value)

    def test_authentication_and_https(self):
        for path in ('/', '/api/test/vessels', '/test-assets/postgres-test.js'):
            self.assertEqual(self.client.get(path).status_code, 401)
        bad = dict(self.headers, Authorization='Basic ' + base64.b64encode('ñ:ñ'.encode()).decode())
        self.assertEqual(self.client.get('/', headers=bad).status_code, 401)
        bad = dict(self.headers, **{'X-Forwarded-Proto': 'http'})
        self.assertEqual(self.client.get('/', headers=bad).status_code, 403)
        self.assertEqual(self.client.get('/', headers={'Authorization': self.headers['Authorization']}).status_code, 403)

    def test_csrf_origin_and_json_guards(self):
        with patch.object(target, 'connection') as db:
            for method, path in (('POST', '/api/test/vessels'), ('PUT', '/api/test/vessels/1'),
                                 ('DELETE', '/api/test/vessels/1'), ('POST', '/api/test/vessels/1/movements')):
                headers = {k:v for k,v in self.headers.items() if k != 'X-CSRF-Token'}
                self.assertEqual(self.client.open(path, method=method, headers=headers, json={}).status_code, 403)
            self.assertEqual(self.client.post('/api/test/vessels', headers=dict(self.headers, Origin='https://evil.invalid'), json={}).status_code, 403)
            self.assertEqual(self.client.post('/api/test/vessels', headers=self.headers, data='bad').status_code, 415)
            for value in ([], 'text', 123, None):
                self.assertEqual(self.client.post('/api/test/vessels', headers=self.headers, data=__import__('json').dumps(value), content_type='application/json').status_code, 400)
            db.assert_not_called()

    def test_connection_rejects_wrong_branch_host_and_database(self):
        for url in ('postgresql://wrong.neon.tech/servamar_demo', 'postgresql://' + target.TEST_HOST + '/production'):
            with patch.dict(os.environ, SERVAMAR_PG_TEST_DATABASE_URL=url), self.assertRaises(RuntimeError):
                target.connection()

    def test_template_assets_and_headers(self):
        response = self.request('GET', '/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('dd/mm/yyyy', response.text)
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertIn("frame-ancestors 'none'", response.headers['Content-Security-Policy'])
        for asset in ('postgres-test.js', 'postgres-test.css'):
            with self.request('GET', '/test-assets/' + asset) as asset_response:
                self.assertEqual(asset_response.status_code, 200)
        self.assertEqual(self.request('GET', '/test-assets/app.js').status_code, 404)

    def test_database_failure_redacted(self):
        with patch.object(target, 'connection', side_effect=RuntimeError('secret-password')):
            response = self.request('GET', '/api/test/vessels')
            self.assertEqual(response.status_code, 503)
            self.assertNotIn('secret-password', response.text)

    def test_database_restrict_violation_is_conflict(self):
        class Restricted(Exception):
            sqlstate = '23001'
        with patch.object(target, 'connection', side_effect=Restricted()):
            self.assertEqual(self.request('GET', '/api/test/vessels').status_code, 409)

    def test_large_payload_returns_413(self):
        response = self.request('POST', '/api/test/vessels', {'name': 'x' * 40000})
        self.assertEqual(response.status_code, 413)

    def test_migration_refuses_wrong_or_pooled_target(self):
        import postgres_test_migrate as migration
        for hostname in ('example.invalid', target.TEST_HOST.replace('.c-4.', '-pooler.c-4.')):
            with patch.dict(os.environ, SERVAMAR_PG_TEST_DATABASE_URL='postgresql://' + hostname + '/servamar_demo'):
                with self.assertRaises(RuntimeError): migration.migrate()


FIXTURE = """
CREATE TABLE {s}.vessels (
    id bigint PRIMARY KEY, declaration text NOT NULL UNIQUE, name text NOT NULL,
    captain text NOT NULL DEFAULT '', registration_number text NOT NULL DEFAULT '', calculation_mode text NOT NULL DEFAULT 'manual', automatic_notices_suspended boolean NOT NULL DEFAULT false, automatic_notices_reason text, stage text NOT NULL, start_date date, expiry_date date,
    validated boolean NOT NULL DEFAULT false, notes text NOT NULL DEFAULT '');
CREATE TABLE {s}.history (
    id bigint PRIMARY KEY, vessel_id bigint NOT NULL REFERENCES {s}.vessels(id) ON DELETE RESTRICT,
    kind text NOT NULL, event_date date, expiry_date date, description text, created_at text);
CREATE TABLE {s}.alert_settings (
    vessel_id bigint NOT NULL REFERENCES {s}.vessels(id) ON DELETE RESTRICT,
    days_before integer NOT NULL CHECK(days_before>=0), enabled boolean NOT NULL DEFAULT true,
    PRIMARY KEY(vessel_id,days_before));
CREATE TABLE {s}.v91_vessel_contacts (
 id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
 vessel_id bigint NOT NULL REFERENCES {s}.vessels(id) ON DELETE RESTRICT,
 contact_role text NOT NULL, full_name text NOT NULL,
 email text, phone text, is_primary boolean NOT NULL DEFAULT false);
CREATE UNIQUE INDEX v91_one_primary_contact ON {s}.v91_vessel_contacts(vessel_id) WHERE is_primary;
CREATE TABLE {s}.v91_documents (
 id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
 vessel_id bigint NOT NULL REFERENCES {s}.vessels(id) ON DELETE RESTRICT);
CREATE TABLE {s}.v91_notification_events (
 id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
 vessel_id bigint NOT NULL REFERENCES {s}.vessels(id) ON DELETE RESTRICT,
 channel text, kind text, due_date date, status text, error_code text);
"""


@unittest.skipUnless(os.getenv('V90_TEST_POSTGRES_URL'), 'Requires isolated PostgreSQL integration connection')
class DatabaseTests(ConsoleTests):
    @classmethod
    def setUpClass(cls):
        import psycopg
        cls.url = os.environ['V90_TEST_POSTGRES_URL']
        cls.schema = 'v90_ci_' + uuid.uuid4().hex
        cls.migration = Path('migrations/v90_test_console.sql').read_text(encoding='utf-8').replace('servamar_test', cls.schema)
        with psycopg.connect(cls.url) as db:
            db.execute('CREATE SCHEMA ' + cls.schema)
            db.execute(FIXTURE.format(s=cls.schema))
            db.execute(cls.migration)
        cls.addClassCleanup(cls.cleanup_schema)

    @classmethod
    def cleanup_schema(cls):
        import psycopg
        # Only the generated fixture schema; no CASCADE and no application tables.
        if not cls.schema.startswith('v90_ci_'):
            raise RuntimeError('Unexpected fixture schema')
        with psycopg.connect(cls.url) as db:
            for name in ('v90_audit', 'v91_notification_events', 'v91_documents', 'v91_vessel_contacts', 'alert_settings', 'history', 'vessels'):
                db.execute('DROP TABLE ' + cls.schema + '.' + name)
            for name in ('v90_vessel_id_seq', 'v90_history_id_seq'):
                db.execute('DROP SEQUENCE ' + cls.schema + '.' + name)
            db.execute('DROP SCHEMA ' + cls.schema)

    @classmethod
    @contextmanager
    def fixture_connection(cls):
        import psycopg
        class Wrapper:
            def __init__(self, db): self.db = db
            def execute(self, sql, params=None):
                return self.db.execute(sql.replace('servamar_test.', cls.schema + '.'), params)
        with psycopg.connect(cls.url, connect_timeout=8, options='-c lock_timeout=5000') as db:
            yield Wrapper(db)

    def setUp(self):
        super().setUp()
        self.connection_patch = patch.object(target, 'connection', self.fixture_connection)
        self.connection_patch.start()
        self.addCleanup(self.connection_patch.stop)

    def create(self, **overrides):
        data = dict(declaration='ST-TEST-' + uuid.uuid4().hex[:12].upper(), name='Ficticia V90',
                    captain='Capitán ficticio', start_date='17/11/2026', expiry_date='17/02/2027')
        data.update(overrides)
        response = self.request('POST', '/api/test/vessels', data)
        self.assertEqual(response.status_code, 201, response.json)
        return response.json['vessel']

    def path(self, vessel): return '/api/test/vessels/' + str(vessel['id'])

    def test_edit_isolated_version_and_audit(self):
        first, second = self.create(), self.create()
        response = self.request('PUT', self.path(first), dict(first, name='Nombre editado', expiry_date='18/02/2027'))
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['vessel']['version'], 2)
        self.assertEqual(response.json['vessel']['expiry_date'], '2027-02-18')
        self.assertEqual(self.request('GET', self.path(second)).json['vessel'], second)
        self.assertEqual(self.request('PUT', self.path(first), first).status_code, 409)
        with self.fixture_connection() as db:
            before, after = db.execute("SELECT before_state,after_state FROM servamar_test.v90_audit WHERE vessel_id=%s AND action='edit'", (first['id'],)).fetchone()
        self.assertEqual(before['name'], first['name'])
        self.assertEqual(after['name'], 'Nombre editado')

    def test_invalid_edit_duplicate_and_not_found(self):
        first, second = self.create(), self.create()
        for changes in ({'name': ''}, {'captain': None}, {'declaration': 'REAL-001'},
                        {'expiry_date': '16/11/2026'}, {'start_date': '31/02/2026'}, {'version': True}):
            self.assertEqual(self.request('PUT', self.path(first), dict(first, **changes)).status_code, 400)
        self.assertEqual(self.request('PUT', self.path(first), dict(first, declaration=second['declaration'])).status_code, 409)
        self.assertEqual(self.request('GET', self.path(first)).json['vessel'], first)
        for suffix in ('', '/movements', '/alerts'):
            self.assertEqual(self.request('GET', '/api/test/vessels/999999999' + suffix).status_code, 404)

    def test_movements_order_dates_no_projection(self):
        vessel = self.create()
        for day in ('20/11/2026', '18/11/2026'):
            response = self.request('POST', self.path(vessel)+'/movements', dict(kind='salida', event_date=day, version=vessel['version'], description='<script>ficticio</script>', expiry_date='01/12/2026'))
            self.assertEqual(response.status_code, 201, response.json)
            vessel = response.json['vessel']
        history = self.request('GET', self.path(vessel)+'/movements').json['movements']
        self.assertEqual([m['event_date'] for m in history], ['2026-11-18', '2026-11-20'])
        self.assertEqual(vessel['stage'], 'ingreso')
        self.assertEqual(vessel['expiry_date'], '2027-02-17')
        self.assertEqual(self.request('PUT', self.path(vessel), dict(vessel, start_date='19/11/2026')).status_code, 400)

    def test_movement_validation_and_stale_retry(self):
        vessel = self.create()
        base = dict(kind='ingreso', event_date='18/11/2026', version=1)
        for change in ({'kind':'invalid'}, {'event_date':''}, {'event_date':'16/11/2026'}, {'expiry_date':'17/11/2026'}, {'description':'x'*2001}):
            self.assertEqual(self.request('POST', self.path(vessel)+'/movements', dict(base, **change)).status_code, 400)
        self.assertEqual(self.request('POST', self.path(vessel)+'/movements', base).status_code, 201)
        self.assertEqual(self.request('POST', self.path(vessel)+'/movements', base).status_code, 409)
        self.assertEqual(len(self.request('GET', self.path(vessel)+'/movements').json['movements']), 1)

    def test_delete_confirmation_and_audit_survive(self):
        vessel, other = self.create(), self.create()
        body = dict(version=1, confirm_declaration=vessel['declaration'])
        self.assertEqual(self.request('DELETE', self.path(vessel), dict(body, confirm_declaration='wrong')).status_code, 400)
        self.assertEqual(self.request('DELETE', self.path(vessel), dict(body, version=99)).status_code, 409)
        self.assertEqual(self.request('DELETE', self.path(vessel), body).status_code, 200)
        self.assertEqual(self.request('GET', self.path(vessel)).status_code, 404)
        self.assertEqual(self.request('GET', self.path(other)).json['vessel'], other)
        with self.fixture_connection() as db:
            audit = db.execute("SELECT before_state FROM servamar_test.v90_audit WHERE vessel_id=%s AND action='delete'", (vessel['id'],)).fetchone()
        self.assertEqual(audit[0]['declaration'], vessel['declaration'])
        self.assertGreater(self.create()['id'], vessel['id'])

    def test_delete_blocks_each_dependency_and_foreign_key(self):
        import psycopg
        for relation in ('history', 'alert_settings'):
            vessel = self.create()
            with self.fixture_connection() as db:
                if relation == 'history':
                    db.execute("INSERT INTO servamar_test.history(vessel_id,kind) VALUES (%s,'ingreso')", (vessel['id'],))
                else:
                    db.execute('INSERT INTO servamar_test.alert_settings(vessel_id,days_before) VALUES (%s,7)', (vessel['id'],))
            self.assertEqual(self.request('DELETE', self.path(vessel), dict(version=1, confirm_declaration=vessel['declaration'])).status_code, 409)
            with self.assertRaises((psycopg.errors.ForeignKeyViolation, psycopg.errors.RestrictViolation)), self.fixture_connection() as db:
                db.execute('DELETE FROM servamar_test.vessels WHERE id=%s', (vessel['id'],))
            with self.fixture_connection() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM servamar_test.'+relation+' WHERE vessel_id=%s', (vessel['id'],)).fetchone()[0], 1)

    def test_failed_audit_rolls_back_edit_delete_movement(self):
        vessel = self.create()
        cases = [('PUT', self.path(vessel), dict(vessel, name='Should rollback')),
                 ('DELETE', self.path(vessel), dict(version=1, confirm_declaration=vessel['declaration'])),
                 ('POST', self.path(vessel)+'/movements', dict(kind='ingreso', event_date='18/11/2026', version=1))]
        for method, path, data in cases:
            with patch.object(target, 'audit', side_effect=RuntimeError('test rollback')):
                self.assertEqual(self.request(method, path, data).status_code, 503)
            self.assertEqual(self.request('GET', self.path(vessel)).json['vessel'], vessel)
        self.assertEqual(self.request('GET', self.path(vessel)+'/movements').json['movements'], [])

    def test_migration_is_repeatable_without_data_loss(self):
        import psycopg
        vessel = self.create()
        with psycopg.connect(self.url) as db: db.execute(self.migration)
        self.assertEqual(self.request('GET', self.path(vessel)).json['vessel'], vessel)
        self.assertGreater(self.create()['id'], vessel['id'])

    def test_simultaneous_edits_and_creates(self):
        vessel = self.create()
        barrier = threading.Barrier(2)
        def edit(name):
            with target.app.test_client() as client:
                barrier.wait()
                return client.put(self.path(vessel), headers=self.headers, json=dict(vessel, name=name)).status_code
        with ThreadPoolExecutor(2) as pool:
            self.assertEqual(sorted(pool.map(edit, ['Edit A', 'Edit B'])), [200,409])
        def create(index):
            with target.app.test_client() as client:
                data = dict(vessel, declaration='ST-TEST-'+uuid.uuid4().hex[:12].upper())
                return client.post('/api/test/vessels', headers=self.headers, json=data)
        with ThreadPoolExecutor(2) as pool: responses = list(pool.map(create, [1,2]))
        self.assertEqual([r.status_code for r in responses], [201,201])
        self.assertNotEqual(responses[0].json['id'], responses[1].json['id'])

    def test_delete_racing_movement_has_no_orphans(self):
        vessel = self.create()
        barrier = threading.Barrier(2)
        def operation(kind):
            with target.app.test_client() as client:
                barrier.wait()
                if kind == 'delete':
                    return client.delete(self.path(vessel), headers=self.headers, json=dict(version=1, confirm_declaration=vessel['declaration'])).status_code
                return client.post(self.path(vessel)+'/movements', headers=self.headers, json=dict(version=1, kind='ingreso', event_date='18/11/2026')).status_code
        with ThreadPoolExecutor(2) as pool: results = list(pool.map(operation, ['delete','move']))
        self.assertIn(results, ([200,404], [409,201]))
        with self.fixture_connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM servamar_test.history h LEFT JOIN servamar_test.vessels v ON v.id=h.vessel_id WHERE v.id IS NULL').fetchone()[0], 0)

    # This unit check must exercise the unpatched guard, not the fixture factory.
    def test_connection_rejects_wrong_branch_host_and_database(self):
        self.connection_patch.stop()
        super().test_connection_rejects_wrong_branch_host_and_database()


@unittest.skipUnless(target.TEST_HOST in os.getenv('V90_TEST_POSTGRES_URL', '').replace('-pooler.', '.'),
                     'Requires the pinned Neon testing endpoint')
class NeonConnectionTests(unittest.TestCase):
    def test_direct_and_pooled_connections_apply_transaction_limits(self):
        url = os.environ['V90_TEST_POSTGRES_URL'].replace('-pooler.c-4.', '.c-4.')
        for connection_url in (url, url.replace('.c-4.', '-pooler.c-4.')):
            with self.subTest(pooled='-pooler.' in connection_url):
                with patch.dict(os.environ, SERVAMAR_PG_TEST_DATABASE_URL=connection_url):
                    with target.connection() as db:
                        row = db.execute("SELECT current_database(),current_setting('statement_timeout'),current_setting('lock_timeout')").fetchone()
                        self.assertEqual(row, ('servamar_demo', '10s', '5s'))


if __name__ == '__main__': unittest.main()
