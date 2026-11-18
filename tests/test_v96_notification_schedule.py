"""Current expiry always owns the reminder plan; no delivery is permitted."""
from datetime import date,timedelta
from pathlib import Path
import os
import unittest
from unittest.mock import patch
import postgres_test_app as target
from postgres_test_notifications import reminder_dates
import test_v94_permits as support


class DateTests(unittest.TestCase):
    def test_thirty_elapsed_days_not_calendar_month_and_inactive_permits(self):
        vessel=dict(stage='ampliacion',expiry_date='2027-11-02',automatic_notices_suspended=True)
        result=reminder_dates(vessel,date(2027,9,1))
        self.assertEqual([r['date'] for r in result],['2027-10-03','2027-10-18','2027-11-01'])
        self.assertEqual([r['days_before'] for r in result],[30,15,1])
        self.assertEqual([r['status'] for r in reminder_dates(vessel,date(2027,10,18))],['elapsed','planned','planned'])
        for change in ({'stage':'salida'},{'stage':'cierre'},{'needs_review':True},{'expiry_date':None}):
            self.assertEqual(reminder_dates(dict(vessel,**change),date(2027,9,1)),[])


@unittest.skipUnless(os.getenv('V90_TEST_POSTGRES_URL'),'Requires isolated PostgreSQL')
class ScheduleTests(support.CalculatedDatabaseTests):
    def plan(self,vessel):
        response=self.request('GET',self.path(vessel)+'/notifications/plan')
        self.assertEqual(response.status_code,200,response.json)
        self.assertFalse(response.json['delivery_enabled'])
        return response.json['plans']

    def active(self,vessel):return [p for p in self.plan(vessel) if p['status']=='planned']

    def assert_current(self,vessel,count=9):
        plans=self.active(vessel);self.assertEqual(len(plans),count,plans)
        for plan in plans:
            self.assertEqual(plan['expiry_date'],vessel['expiry_date'])
            self.assertEqual(date.fromisoformat(plan['date']),date.fromisoformat(vessel['expiry_date'])-timedelta(days=plan['days_before']))
        self.assertEqual(len({(p['date'],p['channel']) for p in plans}),len(plans))

    def test_entry_extension_deposit_edit_and_delete_follow_new_deadline(self):
        vessel=self.create(start_date='04/11/2026',calculation_mode='calculated')
        self.assert_current(vessel);first=vessel['expiry_date']
        vessel,extension=self.add(vessel,'ampliacion','10/11/2026')
        self.assert_current(vessel);second=vessel['expiry_date']
        self.assertNotEqual(first,second);self.assertFalse(vessel['automatic_notices_suspended'])
        self.assertTrue(all(p['status']=='cancelled' for p in self.plan(vessel) if p['expiry_date']==first))
        vessel,deposit=self.add(vessel,'deposito','12/11/2026')
        self.assert_current(vessel);self.assertEqual(vessel['expiry_date'],'2027-11-12')
        path=self.path(vessel)+'/movements/'+str(deposit)
        response=self.request('PUT',path,dict(version=vessel['version'],kind='deposito',event_date='13/11/2026'))
        self.assertEqual(response.status_code,200,response.json);vessel=response.json['vessel']
        self.assertEqual(vessel['expiry_date'],'2027-11-13');self.assert_current(vessel)
        for mid,expected in ((deposit,second),(extension,first)):
            response=self.request('DELETE',self.path(vessel)+'/movements/'+str(mid),dict(version=vessel['version'],confirm_declaration=vessel['declaration']))
            self.assertEqual(response.status_code,200,response.json);vessel=response.json['vessel']
            self.assertEqual(vessel['expiry_date'],expected);self.assert_current(vessel)

    def test_manual_expiry_change_repeated_save_and_restore_no_duplicates(self):
        vessel=self.create();other=self.create();original=vessel['expiry_date']
        other_plan=self.plan(other)
        for expiry in ('2027-03-31','2027-03-31',original):
            response=self.request('PUT',self.path(vessel),dict(vessel,expiry_date=expiry))
            self.assertEqual(response.status_code,200,response.json);vessel=response.json['vessel']
            self.assert_current(vessel)
        self.assertEqual(len(self.plan(vessel)),18)
        self.assertEqual(self.plan(other),other_plan)
        response=self.request('PUT',self.path(vessel),dict(vessel,expiry_date=''))
        self.assertEqual(response.status_code,200,response.json);vessel=response.json['vessel']
        self.assertEqual(self.active(vessel),[])

    def test_legacy_pending_cancelled_sent_and_manual_preserved_no_resend(self):
        vessel=self.create();old=vessel['expiry_date'];due=date.fromisoformat(old)-timedelta(days=30)
        with self.fixture_connection() as db:
            for channel,kind,status in (('email','expiry_30','sent'),('push','expiry_30','pending'),('windows','expiry_30','failed'),('email','manual','pending')):
                db.execute('INSERT INTO servamar_test.v91_notification_events(vessel_id,channel,kind,due_date,status) VALUES (%s,%s,%s,%s,%s)',(vessel['id'],channel,kind,due,status))
        for expiry in ('2027-03-31',old):
            response=self.request('PUT',self.path(vessel),dict(vessel,expiry_date=expiry))
            self.assertEqual(response.status_code,200,response.json);vessel=response.json['vessel']
        self.assert_current(vessel,count=8)
        with self.fixture_connection() as db:
            statuses=db.execute('SELECT status FROM servamar_test.v91_notification_events WHERE vessel_id=%s ORDER BY id',(vessel['id'],)).fetchall()
        self.assertEqual([s[0] for s in statuses],['sent','cancelled','cancelled','pending'])
        self.assertEqual(self.request('POST',self.path(vessel)+'/notifications/send',{}).status_code,403)

    def test_exit_return_and_removed_return_reconcile(self):
        vessel=self.create(start_date='04/11/2026',calculation_mode='calculated');first=vessel['expiry_date']
        vessel,_=self.add(vessel,'salida','05/11/2026');self.assertEqual(self.active(vessel),[])
        vessel,ret=self.add(vessel,'retorno','10/11/2026');self.assert_current(vessel)
        self.assertEqual(vessel['expiry_date'],(date.fromisoformat(first)+timedelta(days=5)).isoformat())
        response=self.request('DELETE',self.path(vessel)+'/movements/'+str(ret),dict(version=vessel['version'],confirm_declaration=vessel['declaration']))
        self.assertEqual(response.status_code,200,response.json);self.assertEqual(self.active(response.json['vessel']),[])

    def test_rollback_invalid_history_and_stale_version_keep_previous_plan(self):
        vessel=self.create(start_date='04/11/2026',calculation_mode='calculated');original=self.plan(vessel)
        with patch.object(target,'audit',side_effect=RuntimeError('test atomicity')):
            response=self.request('POST',self.path(vessel)+'/movements',dict(version=vessel['version'],kind='ampliacion',event_date='10/11/2026'))
        self.assertEqual(response.status_code,503);self.assertEqual(self.plan(vessel),original)
        for data in (dict(version=vessel['version'],kind='retorno',event_date='10/11/2026'),dict(version=999,kind='deposito',event_date='10/11/2026')):
            self.assertEqual(self.request('POST',self.path(vessel)+'/movements',data).status_code,409)
        self.assertEqual(self.plan(vessel),original)

    def test_elapsed_reminders_not_retroactively_scheduled_and_reads_refresh(self):
        vessel=self.create(expiry_date='18/11/2026')
        self.assert_current(vessel,count=3) # Only the 1-day notice is due today.
        with patch('postgres_test_notifications.today_guatemala',return_value=date(2026,11,18)):
            self.assertEqual(self.active(vessel),[])
            self.assertTrue(all(p['status']=='elapsed' for p in self.plan(vessel)))

    def test_migration_clears_v95_latch_and_is_idempotent(self):
        vessel=self.create(expiry_date='17/11/2028')
        migration=Path('migrations/v96_current_expiry_notices.sql').read_text()
        with self.fixture_connection() as db:
            db.execute("UPDATE servamar_test.vessels SET automatic_notices_suspended=TRUE,automatic_notices_reason='deposito' WHERE id=%s",(vessel['id'],))
            db.execute("UPDATE servamar_test.v96_notification_schedule SET status='cancelled' WHERE vessel_id=%s",(vessel['id'],))
            db.execute(migration)
            first=db.execute('SELECT version,automatic_notices_suspended,automatic_notices_reason FROM servamar_test.vessels WHERE id=%s',(vessel['id'],)).fetchone()
            db.execute(migration)
            second=db.execute('SELECT version,automatic_notices_suspended,automatic_notices_reason FROM servamar_test.vessels WHERE id=%s',(vessel['id'],)).fetchone()
        self.assertEqual(first,second);self.assertEqual(first,(vessel['version']+1,False,None));self.assert_current(vessel)

if __name__=='__main__':unittest.main()
