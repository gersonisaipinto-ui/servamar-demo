"""Regression tests: simulated DEMO reminders never send client emails or touch daily history."""
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo
from flask import Flask
import push_demo
import app


class DemoPushSimulationTests(unittest.TestCase):
    def setUp(self):
        self.flask=Flask(__name__)
        self.flask.register_blueprint(push_demo.bp)
        self.flask.testing=True
        self.today=datetime.now(ZoneInfo("America/Guatemala")).date()
        self.target=self.today+timedelta(days=8)
        self.row={
            "vessel_id":"demo-pg-99","declaration":"DEMO-TEST-99",
            "vessel":"FICTICIO","category":"vencimiento",
            "expiry_date":(self.target+timedelta(days=15)).isoformat(),
            "days_before":15,"source":"PostgreSQL DEMO","demo_pg":True
        }

    def post(self,reg="DEMO-TEST-99",confirmation="SIMULAR"):
        with self.flask.test_client() as client:
            return client.post("/api/push/demo-reminder-test",json={
                "registration":reg,"notify_on":self.target.isoformat(),
                "confirmation":confirmation
            })

    def test_requires_demo_mode(self):
        with patch.object(app,"DEMO_MODE",False),patch.object(app,"CLOUD_MODE",True),\
             patch.object(push_demo,"PG_URL","placeholder"):
            self.assertEqual(self.post().status_code,403)

    def test_rejects_non_demo_identity(self):
        with patch.object(app,"DEMO_MODE",True),patch.object(app,"CLOUD_MODE",True),\
             patch.object(push_demo,"PG_URL","placeholder"):
            self.assertEqual(self.post(reg="ST-REAL-001").status_code,400)

    def test_requires_explicit_confirmation(self):
        with patch.object(app,"DEMO_MODE",True),patch.object(app,"CLOUD_MODE",True),\
             patch.object(push_demo,"PG_URL","placeholder"):
            self.assertEqual(self.post(confirmation="").status_code,400)

    def test_rejects_missing_reminder_date_without_sending(self):
        with patch.object(app,"DEMO_MODE",True),patch.object(app,"CLOUD_MODE",True),\
             patch.object(push_demo,"PG_URL","placeholder"),\
             patch.object(app,"planned_alerts_for_day",return_value={"items":[]}),\
             patch.object(push_demo,"send_demo") as sender:
            response=self.post()
        self.assertEqual(response.status_code,409)
        sender.assert_not_called()

    def test_valid_rule_calls_push_only_with_anonymous_payload(self):
        with patch.object(app,"DEMO_MODE",True),patch.object(app,"CLOUD_MODE",True),\
             patch.object(push_demo,"PG_URL","placeholder"),\
             patch.object(app,"planned_alerts_for_day",return_value={"items":[self.row]}),\
             patch.object(push_demo,"send_demo",return_value={
                 "subscribers":2,"accepted":2,"skipped":0,"failed":0
             }) as sender:
            response=self.post()
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.get_json()["matched_alerts"],1)
        args,kwargs=sender.call_args
        payload=args[0]
        self.assertNotIn("DEMO-TEST-99",str(payload))
        self.assertNotIn("FICTICIO",str(payload))
        self.assertTrue(kwargs["day"].startswith("simulation-"))

    def test_same_simulation_generates_same_dedupe_key(self):
        with patch.object(app,"DEMO_MODE",True),patch.object(app,"CLOUD_MODE",True),\
             patch.object(push_demo,"PG_URL","placeholder"),\
             patch.object(app,"planned_alerts_for_day",return_value={"items":[self.row]}),\
             patch.object(push_demo,"send_demo",side_effect=[
                 {"subscribers":2,"accepted":2,"skipped":0,"failed":0},
                 {"subscribers":2,"accepted":0,"skipped":2,"failed":0}
             ]) as sender:
            a=self.post()
            b=self.post()
        self.assertEqual(a.status_code,200)
        self.assertEqual(b.status_code,200)
        self.assertTrue(b.get_json()["repeated"])
        self.assertEqual(sender.call_args_list[0].kwargs["day"],
                         sender.call_args_list[1].kwargs["day"])


if __name__=="__main__":
    unittest.main()
