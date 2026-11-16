"""Integration tests use ONLY ephemeral local PostgreSQL CI service."""
import os
import unittest

import psycopg

from neon_migration import TABLE_DDL, TABLES, MIGRATION_ID, migrate_demo

ADMIN_URL = os.getenv("V67_TEST_POSTGRES_URL", "")
SOURCE_URL = "postgresql://postgres:ci-password@127.0.0.1:5432/source_demo"
TARGET_URL = "postgresql://postgres:ci-password@127.0.0.1:5432/target_demo"
BLOCKED_URL = "postgresql://postgres:ci-password@127.0.0.1:5432/blocked_demo"


@unittest.skipUnless(ADMIN_URL, "CI PostgreSQL URL missing")
class V67MigrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with psycopg.connect(ADMIN_URL, autocommit=True) as db:
            for name in ("target_demo", "blocked_demo"):
                db.execute(f"CREATE DATABASE {name}")
        with psycopg.connect(SOURCE_URL) as src:
            for ddl in TABLE_DDL:
                src.execute(ddl)
            src.execute("""INSERT INTO servamar_demo_vessels
                (id,registration,vessel_name,captain,stage,entry_date,
                 movement_date,due_date,notes,version)
                VALUES(41,'DEMO-041','FICTICIA CI','CAPITAN CI','ingreso',
                '2026-11-01','2026-11-01','2027-01-30','sin documentos',3)""")
            src.execute("""INSERT INTO servamar_demo_movements
                (id,vessel_id,kind,event_date,stage_before,due_before,
                stage_after,due_after) VALUES(14,41,'salida','2026-11-02',
                'ingreso','2027-01-30','salida','2027-01-30')""")
            src.execute("""INSERT INTO servamar_demo_movement_corrections
                (id,vessel_id,movement_id,action,registration,before_state,after_state)
                VALUES(5,41,14,'edit','DEMO-041','{"old":1}'::jsonb,'{"new":1}'::jsonb)""")
            src.execute("""INSERT INTO servamar_demo_vessel_audit
                (id,vessel_id,action,registration) VALUES(7,41,'create','DEMO-041')""")
            src.execute("""INSERT INTO servamar_push_settings(id,pem)
                VALUES('vapid','CI-FAKE-PRIVATE-KEY-DO-NOT-USE')""")
            src.execute("""INSERT INTO servamar_push_subscriptions(id,content)
                VALUES('ci-device','{"fake":true}')""")
        with psycopg.connect(BLOCKED_URL) as blocked:
            for ddl in TABLE_DDL:
                blocked.execute(ddl)
            blocked.execute("""INSERT INTO servamar_push_daily_targets(day,sub_id)
                VALUES('2026-11-16','already-there')""")

    def test_migration_and_idempotence(self):
        report = migrate_demo(SOURCE_URL, TARGET_URL)
        self.assertEqual(report["status"], "migrated")
        self.assertEqual(report["counts"]["servamar_demo_vessels"], 1)
        self.assertEqual(report["counts"]["servamar_demo_movement_corrections"], 1)
        self.assertEqual(report["counts"]["servamar_push_settings"], 1)
        with psycopg.connect(TARGET_URL) as target:
            self.assertEqual(target.execute(
                "SELECT COUNT(*) FROM servamar_migration_receipts WHERE id=%s",
                (MIGRATION_ID,)).fetchone()[0], 1)
            self.assertEqual(target.execute(
                "SELECT registration FROM servamar_demo_vessels WHERE id=41"
            ).fetchone()[0], "DEMO-041")
            self.assertEqual(target.execute(
                "SELECT after_state->>'new' FROM servamar_demo_movement_corrections"
            ).fetchone()[0], "1")
            self.assertEqual(target.execute(
                "SELECT pem FROM servamar_push_settings WHERE id='vapid'"
            ).fetchone()[0], "CI-FAKE-PRIVATE-KEY-DO-NOT-USE")
            new_id = target.execute("""INSERT INTO servamar_demo_vessels
                (registration,vessel_name,captain,stage,entry_date,
                 movement_date,due_date) VALUES
                ('DEMO-042','OTRA FICTICIA','TEST','ingreso',
                 '2026-11-01','2026-11-01','2027-01-30')
                RETURNING id""").fetchone()[0]
            self.assertGreater(new_id, 41)
        second = migrate_demo(SOURCE_URL, TARGET_URL)
        self.assertEqual(second["status"], "already_migrated")
        with psycopg.connect(SOURCE_URL) as source:
            self.assertEqual(source.execute(
                "SELECT COUNT(*) FROM servamar_demo_vessels"
            ).fetchone()[0], 1)

    def test_nonempty_target_not_overwritten(self):
        with self.assertRaisesRegex(RuntimeError, "ya contiene registros"):
            migrate_demo(SOURCE_URL, BLOCKED_URL)
        with psycopg.connect(BLOCKED_URL) as target:
            self.assertEqual(target.execute(
                "SELECT COUNT(*) FROM servamar_push_daily_targets"
            ).fetchone()[0], 1)
            self.assertEqual(target.execute(
                "SELECT COUNT(*) FROM servamar_demo_vessels"
            ).fetchone()[0], 0)

    def test_same_source_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "distintas"):
            migrate_demo(SOURCE_URL, SOURCE_URL)


if __name__ == "__main__":
    unittest.main()
