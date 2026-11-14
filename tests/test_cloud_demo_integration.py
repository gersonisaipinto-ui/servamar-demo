"""Prueba integración solo en memoria: PostgreSQL real no se consulta."""
import unittest
from datetime import date
from unittest.mock import patch
import app


class DemoIntegrationTests(unittest.TestCase):
    def test_cloud_demo_reminders_are_included_in_daily_plan(self):
        sample={"vessel_id":"demo-pg-77","declaration":"DEMO-TEST-77",
                "vessel":"EMBARCACIÓN FICTICIA","category":"vencimiento",
                "expiry_date":"2026-12-13","days_before":30,
                "recipients":["administracion"],"source":"PostgreSQL DEMO","demo_pg":True}
        with patch.object(app,"DEMO_MODE",True),patch.object(app,"CLOUD_MODE",True),\
             patch("demo_vessels.demo_reminders_for_day",return_value=[sample]):
            schedule=app.planned_alerts_for_day(date(2026,11,13))
        self.assertEqual(sum(x.get("vessel_id")=="demo-pg-77" for x in schedule["items"]),1)
        self.assertEqual(schedule["count"],len(schedule["items"]))
        self.assertTrue(all(x.get("vessel_id")!="demo-pg-77" or
                            x.get("source")=="PostgreSQL DEMO" for x in schedule["items"]))

    def test_local_demo_has_no_postgres_dependency(self):
        with patch.object(app,"DEMO_MODE",True),patch.object(app,"CLOUD_MODE",False),\
             patch("demo_vessels.demo_reminders_for_day",side_effect=AssertionError("Must not access PostgreSQL")):
            plan=app.planned_alerts_for_day(date(2026,11,13))
        self.assertEqual(plan["count"],len(plan["items"]))


if __name__=="__main__":
    unittest.main()
