"""Offline tests with fictitious vessels only; never contacts Render or customers."""
import unittest
from datetime import date,timedelta
from zoneinfo import ZoneInfo
from datetime import datetime

import app


class ReminderTests(unittest.TestCase):
    def setUp(self):
        self.today = date.today()
        self.demo = app.DEMO_MODE
        self.assertTrue(self.demo, "Tests must run with SERVAMAR_DEMO_MODE=YES")

    def planned(self, offset):
        return app.planned_alerts_for_day(self.today + timedelta(days=offset))["items"]

    def test_30_day_notice(self):
        items=self.planned(0)
        self.assertTrue(any(i["declaration"]=="ST-DEMO-002" and
                            i["days_before"]==30 and
                            i["category"]=="vencimiento" for i in items))

    def test_15_day_notice(self):
        items=self.planned(15)
        self.assertTrue(any(i["declaration"]=="ST-DEMO-002" and
                            i["days_before"]==15 for i in items))

    def test_1_day_notice(self):
        items=self.planned(14)
        self.assertTrue(any(i["declaration"]=="ST-DEMO-001" and
                            i["days_before"]==1 for i in items))

    def test_longer_expiry_30_day_notice(self):
        items=self.planned(20)
        self.assertTrue(any(i["declaration"]=="ST-DEMO-003" and
                            i["days_before"]==30 for i in items))

    def test_temporary_exit_schedule_rules(self):
        # Declaración independiente y ficticia; nunca persistida en producción.
        with app.conn() as c:
            c.execute("DELETE FROM history WHERE vessel_id IN (SELECT id FROM vessels WHERE declaration='ST-DEMO-SALIDA')")
            c.execute("DELETE FROM vessels WHERE declaration='ST-DEMO-SALIDA'")
            leave=self.today-timedelta(days=60)
            arrival=self.today-timedelta(days=75)
            finish=self.today+timedelta(days=180)
            cursor=c.execute("""INSERT INTO vessels
                (declaration,name,captain,stage,start_date,expiry_date,validated,notes)
                VALUES(?,?,?,?,?,?,?,?)""",
                ("ST-DEMO-SALIDA","TEST VESSEL","TEST CAPTAIN","ingreso",
                 arrival.isoformat(),finish.isoformat(),1,"FICTICIOUS"))
            vid=cursor.lastrowid
            c.execute("""INSERT INTO history(vessel_id,kind,event_date,description)
                VALUES(?,?,?,?)""",(vid,"salida",leave.isoformat(),"Fictitious departure"))
        try:
            rows=app.departure_reminder_rows(app.conn(),self.today,0)
            self.assertTrue(any(r["declaration"]=="ST-DEMO-SALIDA" and
                                r["days_before"]==30 for r in rows))
        finally:
            with app.conn() as c:
                c.execute("DELETE FROM history WHERE vessel_id=?",(vid,))
                c.execute("DELETE FROM vessels WHERE id=?",(vid,))


if __name__=="__main__":
    unittest.main()
