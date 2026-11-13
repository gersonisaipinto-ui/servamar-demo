"""Pruebas aisladas de auditoría de notificaciones, sin servicios externos."""
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import push_demo


class PushAuditTests(unittest.TestCase):
    def setUp(self):
        self.assertFalse(push_demo.PG_URL, "Las pruebas deben usar SQLite temporal, nunca PostgreSQL real.")
        self.temp = tempfile.TemporaryDirectory()
        self.old_path = push_demo.dbpath
        push_demo.dbpath = Path(self.temp.name) / "push_test.sqlite3"
        with sqlite3.connect(push_demo.dbpath) as db:
            db.execute("""CREATE TABLE daily_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT NOT NULL, status TEXT NOT NULL, alerts INTEGER NOT NULL,
                accepted INTEGER NOT NULL, failed INTEGER NOT NULL, checked_at TEXT NOT NULL)""")
            db.execute("""CREATE TABLE daily_targets (
                day TEXT NOT NULL, sub_id TEXT NOT NULL, PRIMARY KEY(day,sub_id))""")
            db.execute("""CREATE TABLE daily_delivery (
                day TEXT PRIMARY KEY, status TEXT NOT NULL, count INTEGER NOT NULL,
                recipients INTEGER NOT NULL, completed_at TEXT NOT NULL)""")

    def tearDown(self):
        push_demo.dbpath = self.old_path
        self.temp.cleanup()

    def test_audit_no_alerts_and_failed(self):
        push_demo.record_check("2026-11-13", "no_alerts", 0, 0, 0)
        push_demo.record_check("2026-11-14", "failed", 1, 1, 1)
        rows = push_demo.checks_history()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["status"], "failed")
        self.assertEqual(rows[0]["failed"], 1)
        self.assertEqual(rows[1]["status"], "no_alerts")

    def test_daily_device_deduplication(self):
        self.assertFalse(push_demo.already_delivered("2026-11-15", "test-device"))
        push_demo.record_target("2026-11-15", "test-device")
        push_demo.record_target("2026-11-15", "test-device")
        self.assertTrue(push_demo.already_delivered("2026-11-15", "test-device"))
        self.assertFalse(push_demo.already_delivered("2026-11-16", "test-device"))
        with sqlite3.connect(push_demo.dbpath) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM daily_targets").fetchone()[0], 1)


    def test_backup_run_and_new_device(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        import app
        plan = {"count": 1, "items": [{"category": "vencimiento"}]}
        first = {"accepted": 2, "failed": 0, "skipped": 0, "subscribers": 2}
        second = {"accepted": 0, "failed": 0, "skipped": 2, "subscribers": 2}
        third = {"accepted": 1, "failed": 0, "skipped": 2, "subscribers": 3}
        with patch.object(app, "planned_alerts_for_day", return_value=plan), \
             patch.object(push_demo, "send_demo", side_effect=[first,second,third]) as sender:
            a,code1=push_demo.daily_check()
            b,code2=push_demo.daily_check()
            c,code3=push_demo.daily_check()
        self.assertEqual((code1,code2,code3),(200,200,200))
        self.assertEqual(sender.call_count,3)
        self.assertEqual(a.get_json()["accepted"],2)
        self.assertTrue(b.get_json()["already_sent"])
        self.assertEqual(b.get_json()["sent_now"],0)
        self.assertEqual(c.get_json()["accepted"],1)
        self.assertFalse(c.get_json()["already_sent"])
        self.assertEqual(len(push_demo.checks_history()),3)


if __name__ == "__main__":
    unittest.main()
