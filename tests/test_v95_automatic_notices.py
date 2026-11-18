"""Persistent automatic-notice suppression, tested in isolated PostgreSQL."""
from datetime import date
from pathlib import Path
import os
import unittest
from unittest.mock import patch
import postgres_test_app as target
from postgres_test_notifications import preview
import test_v93_functional as support


class PreviewTests(unittest.TestCase):
    def test_suspension_removes_automatic_reminders_but_keeps_manual_preview(self):
        vessel=dict(name='Ficticia',expiry_date='2027-11-02',calculation_mode='calculated',
                    automatic_notices_suspended=True,automatic_notices_reason='deposito')
        result=preview(vessel)
        self.assertEqual(result['reminders'],[])
        self.assertFalse(result['automatic']['email_enabled'])
        self.assertFalse(result['automatic']['notifications_enabled'])
        self.assertIn('depósito',result['warning'])
        self.assertIn('Hola',result['body'])
        self.assertFalse(result['delivery_enabled'])


@unittest.skipUnless(os.getenv('V90_TEST_POSTGRES_URL'),'Requires isolated PostgreSQL')
class SuppressionTests(support.FunctionalTests):
    def setUp(self):
        super().setUp()
        for module in ('postgres_test_permits','postgres_test_reports','postgres_test_notifications'):
            p=patch(module+'.today_guatemala',return_value=date(2026,11,17));p.start();self.addCleanup(p.stop)

    def seed(self,vessel):
        with self.fixture_connection() as db:
            for days in (30,15,1):
                db.execute('INSERT INTO servamar_test.alert_settings(vessel_id,days_before,enabled) VALUES (%s,%s,TRUE)',(vessel['id'],days))
            for channel,kind,status in (('email','expiry_30','pending'),('push','expiry_30','failed'),
                                        ('windows','expiry_30','pending'),('email','expiry_15','sent'),('email','manual','pending')):
                db.execute('INSERT INTO servamar_test.v91_notification_events(vessel_id,channel,kind,due_date,status) '
                           "VALUES (%s,%s,%s,'2027-01-01',%s)",(vessel['id'],channel,kind,status))

    def events(self,vessel):
        with self.fixture_connection() as db:
            return db.execute('SELECT channel,kind,status,error_code FROM servamar_test.v91_notification_events '
                              'WHERE vessel_id=%s ORDER BY id',(vessel['id'],)).fetchall()

    def add(self,vessel,kind):
        return self.request('POST',self.path(vessel)+'/movements',dict(version=vessel['version'],kind=kind,event_date='10/11/2026'))

    def test_each_movement_disables_both_channels_and_only_own_automatic_events(self):
        for kind in ('ampliacion','deposito'):
            for mode in ('manual','calculated'):
                with self.subTest(kind=kind,mode=mode):
                    vessel=self.create(start_date='01/11/2026',calculation_mode=mode)
                    other=self.create();self.seed(vessel);self.seed(other)
                    response=self.add(vessel,kind);self.assertEqual(response.status_code,201,response.json)
                    current=response.json['vessel']
                    self.assertTrue(current['automatic_notices_suspended']);self.assertEqual(current['automatic_notices_reason'],kind)
                    alerts=self.request('GET',self.path(vessel)+'/alerts').json['alerts']
                    self.assertTrue(all(not a['enabled'] for a in alerts));self.assertEqual(len(alerts),3)
                    events=self.events(vessel)
                    self.assertEqual([r[2] for r in events],['cancelled','cancelled','cancelled','sent','pending'])
                    self.assertTrue(all(r[3]=='automatic_notices_suspended' for r in events[:3]))
                    self.assertEqual([r[2] for r in self.events(other)],['pending','failed','pending','sent','pending'])
                    with self.fixture_connection() as db:
                        logged=db.execute("SELECT after_state FROM servamar_test.v90_audit WHERE vessel_id=%s AND action='movement' ORDER BY id DESC LIMIT 1",(vessel['id'],)).fetchone()[0]
                    self.assertEqual(logged['automatic_notices']['events_cancelled'],3)
                    self.assertEqual(logged['automatic_notices']['alerts_disabled'],3)

    def test_edit_into_extension_suppresses_and_delete_never_reenables(self):
        vessel=self.create(start_date='01/11/2026');self.seed(vessel)
        response=self.add(vessel,'salida');self.assertEqual(response.status_code,201,response.json)
        vessel=response.json['vessel'];mid=response.json['id']
        self.assertFalse(vessel['automatic_notices_suspended'])
        path=self.path(vessel)+'/movements/'+str(mid)
        response=self.request('PUT',path,dict(version=vessel['version'],kind='ampliacion',event_date='10/11/2026'))
        self.assertEqual(response.status_code,200,response.json);vessel=response.json['vessel']
        self.assertTrue(vessel['automatic_notices_suspended'])
        response=self.request('PUT',path,dict(version=vessel['version'],kind='salida',event_date='10/11/2026'))
        self.assertEqual(response.status_code,200,response.json);vessel=response.json['vessel']
        self.assertTrue(vessel['automatic_notices_suspended'])
        response=self.request('DELETE',path,dict(version=vessel['version'],confirm_declaration=vessel['declaration']))
        self.assertEqual(response.status_code,200,response.json);vessel=response.json['vessel']
        self.assertTrue(vessel['automatic_notices_suspended'])
        response=self.request('PUT',self.path(vessel),dict(vessel,automatic_notices_suspended=False,automatic_notices_reason=None))
        self.assertEqual(response.status_code,200,response.json)
        self.assertTrue(response.json['vessel']['automatic_notices_suspended'])
        result=self.request('GET',self.path(vessel)+'/notifications/preview')
        self.assertEqual(result.status_code,200,result.json);self.assertEqual(result.json['reminders'],[])

    def test_audit_failure_rolls_back_suspension_and_cancellations(self):
        vessel=self.create(start_date='01/11/2026');self.seed(vessel)
        original=self.events(vessel)
        with patch.object(target,'audit',side_effect=RuntimeError('test atomicity')):
            response=self.add(vessel,'deposito')
        self.assertEqual(response.status_code,503,response.json)
        self.assertEqual(self.request('GET',self.path(vessel)).json['vessel'],vessel)
        self.assertEqual(self.events(vessel),original)
        self.assertTrue(all(a['enabled'] for a in self.request('GET',self.path(vessel)+'/alerts').json['alerts']))
        self.assertEqual(self.request('GET',self.path(vessel)+'/movements').json['movements'],[])

    def test_invalid_and_stale_movements_leave_notices_untouched(self):
        vessel=self.create(start_date='01/01/2026',calculation_mode='calculated');self.seed(vessel)
        original=self.events(vessel)
        # November is after the calculated April expiry.
        self.assertEqual(self.add(vessel,'ampliacion').status_code,409)
        self.assertFalse(self.request('GET',self.path(vessel)).json['vessel']['automatic_notices_suspended'])
        self.assertEqual(self.events(vessel),original)
        self.assertEqual(self.request('POST',self.path(vessel)+'/movements',dict(version=999,kind='deposito',event_date='01/02/2026')).status_code,409)
        self.assertEqual(self.events(vessel),original)

    def test_backfill_is_idempotent_and_preserves_sent_and_manual_events(self):
        vessel=self.create(start_date='01/11/2026');self.seed(vessel)
        with self.fixture_connection() as db:
            # A pre-V95 fictional movement that was not processed by the new API.
            db.execute("INSERT INTO servamar_test.history(vessel_id,kind,event_date) VALUES (%s,'deposito','2026-11-10')",(vessel['id'],))
            migration=Path('migrations/v95_stop_automatic_notices.sql').read_text()
            db.execute(migration)
            first=db.execute('SELECT version,automatic_notices_suspended,automatic_notices_reason FROM servamar_test.vessels WHERE id=%s',(vessel['id'],)).fetchone()
            db.execute(migration)
            second=db.execute('SELECT version,automatic_notices_suspended,automatic_notices_reason FROM servamar_test.vessels WHERE id=%s',(vessel['id'],)).fetchone()
        self.assertEqual(first,second);self.assertEqual(first,(vessel['version']+1,True,'deposito'))
        self.assertEqual([r[2] for r in self.events(vessel)],['cancelled','cancelled','cancelled','sent','pending'])

if __name__=='__main__':unittest.main()
