"""Confirmed permit boundaries and transactional replay in PostgreSQL."""
from datetime import date,timedelta
import os
import unittest
from unittest.mock import patch
import postgres_test_permits as permits
import test_v93_functional as support


def movement(kind,event,id=1):return dict(id=id,kind=kind,event_date=event)


class RuleTests(unittest.TestCase):
    today=date(2027,12,31)
    entry=date(2026,1,1)

    def project(self,movements=(),entry=None,today=None):
        return permits.calculate(entry or self.entry,list(movements),today or self.today)

    def test_confirmed_option_c(self):
        entry=date(2026,11,4)
        self.assertEqual(self.project(entry=entry)['expiry_date'],'2027-02-02')
        result=self.project([movement('ampliacion','2027-02-02')],entry=entry)
        self.assertEqual(result['expiry_date'],'2027-11-02')
        self.assertEqual(result['stage'],'ampliacion')

    def test_month_end_leap_year_and_deposit_anchor(self):
        self.assertEqual(permits.add_months(date(2026,5,31),9),date(2027,2,28))
        result=self.project([movement('deposito','2024-02-29')],entry=date(2024,1,1))
        self.assertEqual(result['expiry_date'],'2025-02-28')
        with self.assertRaises(permits.PermitError):
            self.project([movement('deposito','2024-02-29'),movement('salida','2024-03-01',2)],entry=date(2024,1,1))

    def test_returns_zero_37_89_90_91_days(self):
        departure=date(2026,1,5)
        for days in (0,37,89,90,91):
            with self.subTest(days=days):
                result=self.project([movement('salida',departure),movement('retorno',departure+timedelta(days=days),2)])
                self.assertEqual(result['stage'],'ingreso' if days<=90 else 'cierre')
                self.assertEqual(result['days_added'],days if days<=90 else 0)
                self.assertEqual(result['expiry_date'],(self.entry+timedelta(days=90+(days if days<=90 else 0))).isoformat())

    def test_open_exit_closes_only_after_day90_and_caps_counter(self):
        departure=date(2026,1,5);events=[movement('salida',departure)]
        for days in (89,90,91,300):
            result=self.project(events,today=departure+timedelta(days=days))
            self.assertEqual(result['stage'],'salida' if days<=90 else 'cierre')
            self.assertEqual(result['days_out'],min(days,90))
            self.assertFalse(result['needs_review'])
        self.assertIn('se cumplieron el 05/04/2026',self.project(events)['plazo'])

    def test_multiple_exits_and_extension_after_return(self):
        events=[movement('salida','2026-01-05'),movement('retorno','2026-02-11',2),
                movement('ampliacion','2026-02-12',3),movement('salida','2026-03-01',4),movement('retorno','2026-03-06',5)]
        result=self.project(events)
        self.assertEqual(result['days_added'],42)
        expected=permits.add_months(self.entry+timedelta(days=90+37),9)+timedelta(days=5)
        self.assertEqual(result['expiry_date'],expected.isoformat())
        self.assertEqual(self.project(events),result)
        self.assertEqual(events[0]['event_date'],'2026-01-05')

    def test_invalid_transitions_and_future_dates(self):
        cases=[ [movement('retorno','2026-01-05')],
                [movement('salida','2026-01-05'),movement('salida','2026-01-06',2)],
                [movement('ampliacion','2026-02-01'),movement('ampliacion','2026-02-02',2)],
                [movement('ampliacion','2026-04-02')],
                [movement('ingreso','2026-01-02')],
                [movement('salida','2025-12-31')],
                [movement('other','2026-01-02')],
                [movement('ingreso',None)] ]
        for events in cases:
            with self.subTest(events=events),self.assertRaises(permits.PermitError):self.project(events)
        with self.assertRaises(permits.PermitError):self.project([movement('salida','2027-01-01')],today=date(2026,11,17))

    def test_expired_exit_requires90_days_and_a_new_ingreso(self):
        exit_date=date(2026,4,2)
        with self.assertRaises(permits.PermitError):
            self.project([movement('salida',exit_date),movement('retorno',exit_date+timedelta(days=89),2)])
        events=[movement('salida',exit_date),movement('retorno',exit_date+timedelta(days=90),2)]
        self.assertEqual(self.project(events)['stage'],'cierre')
        events.append(movement('ingreso',exit_date+timedelta(days=90),3))
        result=self.project(events)
        self.assertEqual(result['stage'],'ingreso');self.assertEqual(result['days_added'],0)
        self.assertEqual(result['expiry_date'],(exit_date+timedelta(days=180)).isoformat())

    def test_expired_exit_on_deadline_still_preserves_permit(self):
        deadline=self.entry+timedelta(days=90)
        result=self.project([movement('salida',deadline),movement('retorno',deadline+timedelta(days=90),2)])
        self.assertEqual(result['stage'],'ingreso');self.assertEqual(result['days_added'],90)

    def test_explicit_closure_not_reopened_by_short_return(self):
        with self.assertRaises(permits.PermitError):
            self.project([movement('salida','2026-01-05'),movement('cierre','2026-01-06',2),movement('retorno','2026-01-10',3)])


@unittest.skipUnless(os.getenv('V90_TEST_POSTGRES_URL'),'Requires isolated PostgreSQL')
class CalculatedDatabaseTests(support.FunctionalTests):
    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        import psycopg
        super().setUpClass()
        migration=Path('migrations/v94_confirmed_permits.sql').read_text().replace('servamar_test',cls.schema)
        with psycopg.connect(cls.url) as db:
            db.execute(migration)
            db.execute(migration)

    def setUp(self):
        super().setUp()
        for module in ('postgres_test_permits','postgres_test_reports','postgres_test_notifications'):
            patcher=patch(module+'.today_guatemala',return_value=date(2026,11,17));patcher.start();self.addCleanup(patcher.stop)

    def calculated(self):
        return self.create(calculation_mode='calculated',start_date='01/01/2026',expiry_date='',name='Ficticia calculada')

    def add(self,vessel,kind,event):
        response=self.request('POST',self.path(vessel)+'/movements',dict(version=vessel['version'],kind=kind,event_date=event))
        self.assertEqual(response.status_code,201,response.json)
        return response.json['vessel'],response.json['id']

    def test_calculated_creation_and_explicit_manual_preservation(self):
        manual=self.create();self.assertEqual(manual['calculation_mode'],'manual');self.assertEqual(manual['expiry_date'],'2027-02-17')
        vessel=self.calculated();self.assertEqual(vessel['expiry_date'],'2026-04-01')
        self.assertEqual(vessel['calculation_rule'],permits.RULE)
        response=self.request('PUT',self.path(vessel),dict(vessel,expiry_date='01/01/2099'))
        self.assertEqual(response.status_code,200,response.json);self.assertEqual(response.json['vessel']['expiry_date'],'2026-04-01')
        self.assertEqual(self.request('POST','/api/test/vessels',dict(declaration='ST-TEST-NO-ENTRY',name='Ficticia',captain='Ficticio',calculation_mode='calculated')).status_code,409)

    def test_edit_and_delete_return_replay_without_double_count(self):
        vessel=self.calculated();vessel,exit_id=self.add(vessel,'salida','05/01/2026')
        vessel,return_id=self.add(vessel,'retorno','11/02/2026')
        self.assertEqual(vessel['days_added'],37);self.assertEqual(vessel['expiry_date'],'2026-05-08')
        path=self.path(vessel)+'/movements/'+str(return_id)
        response=self.request('PUT',path,dict(version=vessel['version'],kind='retorno',event_date='05/04/2026'))
        self.assertEqual(response.status_code,200,response.json);vessel=response.json['vessel']
        self.assertEqual(vessel['days_added'],90);self.assertEqual(vessel['expiry_date'],'2026-06-30')
        self.assertTrue(response.json['projection_applied'])
        invalid=self.request('DELETE',self.path(vessel)+'/movements/'+str(exit_id),dict(version=vessel['version'],confirm_declaration=vessel['declaration']))
        self.assertEqual(invalid.status_code,409)
        self.assertEqual(self.request('GET',self.path(vessel)).json['vessel']['version'],vessel['version'])
        response=self.request('DELETE',path,dict(version=vessel['version'],confirm_declaration=vessel['declaration']))
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(response.json['vessel']['stage'],'cierre');self.assertEqual(response.json['vessel']['days_added'],0)

    def test_invalid_replay_rolls_back_rows_projection_and_audit(self):
        vessel=self.calculated()
        path=self.path(vessel)+'/movements'
        response=self.request('POST',path,dict(version=vessel['version'],kind='retorno',event_date='01/02/2026'))
        self.assertEqual(response.status_code,409,response.json)
        self.assertEqual(self.request('GET',path).json['movements'],[])
        self.assertEqual(self.request('GET',self.path(vessel)).json['vessel'],vessel)
        with self.fixture_connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM servamar_test.v90_audit WHERE vessel_id=%s AND action='movement'",(vessel['id'],)).fetchone()[0],0)

    def test_switching_manual_to_calculated_replays_and_validates_history(self):
        vessel=self.create(start_date='01/01/2026',expiry_date='01/01/2027')
        vessel,_=self.add(vessel,'retorno','11/02/2026')
        response=self.request('PUT',self.path(vessel),dict(vessel,calculation_mode='calculated'))
        self.assertEqual(response.status_code,409,response.json)
        current=self.request('GET',self.path(vessel)).json['vessel']
        self.assertEqual(current['calculation_mode'],'manual');self.assertEqual(current['version'],vessel['version'])
        vessel,_=self.add(vessel,'salida','05/01/2026')
        response=self.request('PUT',self.path(vessel),dict(vessel,calculation_mode='calculated'))
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(response.json['vessel']['days_added'],37)
        self.assertEqual(response.json['vessel']['expiry_date'],'2026-05-08')

    def test_search_export_and_notifications_share_effective_expiry(self):
        vessel=self.create(start_date='04/11/2026',expiry_date='',calculation_mode='calculated',name='Calc-'+__import__('uuid').uuid4().hex)
        self.assertEqual(vessel['expiry_date'],'2027-02-02')
        initial=self.request('GET',self.path(vessel)+'/notifications/preview').json
        self.assertEqual([r['days_before'] for r in initial['reminders']],[30,15,1])
        self.assertEqual(initial['reminders'][0]['date'],'2027-01-03')
        vessel,_=self.add(vessel,'ampliacion','10/11/2026')
        self.assertEqual(vessel['expiry_date'],'2027-11-02')
        query='q='+vessel['name']
        search=self.request('GET','/api/test/search?'+query)
        self.assertEqual(search.json['vessels'][0]['expiry_date'],vessel['expiry_date'])
        self.assertIn('02/11/2027',self.request('GET','/api/test/export.csv?'+query).text)
        preview=self.request('GET',self.path(vessel)+'/notifications/preview')
        self.assertEqual(preview.status_code,200,preview.json);self.assertFalse(preview.json['manual_dates']);self.assertFalse(preview.json['delivery_enabled'])
        self.assertEqual([r['days_before'] for r in preview.json['reminders']],[30,15,1])
        self.assertEqual(preview.json['reminders'][0]['date'],'2027-10-03')
        self.assertFalse(preview.json['automatic']['suspended'])

    def test_daily_closure_is_reflected_in_reads_without_background_jobs(self):
        vessel=self.create(start_date='01/08/2026',calculation_mode='calculated',expiry_date='',name='Daily-'+__import__('uuid').uuid4().hex)
        vessel,_=self.add(vessel,'salida','19/08/2026') # 90 days to Nov 17.
        self.assertEqual(vessel['stage'],'salida');self.assertEqual(vessel['days_out'],90)
        with patch('postgres_test_permits.today_guatemala',return_value=date(2026,11,18)),patch('postgres_test_reports.today_guatemala',return_value=date(2026,11,18)):
            detail=self.request('GET',self.path(vessel)).json['vessel']
            self.assertEqual(detail['stage'],'cierre');self.assertEqual(detail['days_out'],90)
            search=self.request('GET','/api/test/search?q='+vessel['name']+'&stage=cierre')
            self.assertEqual(search.json['count'],1,search.json)
            self.assertEqual(search.json['vessels'][0]['stage'],'cierre')
            self.assertEqual(self.request('GET',self.path(vessel)+'/notifications/preview').status_code,409)

    def test_manual_extension_preview_and_save_are_atomic(self):
        vessel=self.create(start_date='04/11/2026',expiry_date='04/02/2027')
        path=self.path(vessel)+'/movements'
        body=dict(version=vessel['version'],kind='ampliacion',event_date='',apply_calculation=True)
        before=self.request('GET',self.path(vessel)+'/notifications/plan').json
        preview=self.request('POST',path+'/preview',body)
        self.assertEqual(preview.status_code,200,preview.json)
        self.assertEqual(preview.json['projection']['expiry_date'],'2027-11-02')
        self.assertIn('02/02/2027 + 9 meses calendario = 02/11/2027',preview.json['projection']['explanation'])
        self.assertEqual(preview.json['effective_event_date'],'2026-11-17')
        self.assertTrue(preview.json['mode_will_change'])
        self.assertFalse(preview.json['delivery_enabled'])
        self.assertEqual(self.request('GET',self.path(vessel)).json['vessel'],vessel)
        self.assertEqual(self.request('GET',path).json['movements'],[])
        self.assertEqual(self.request('GET',self.path(vessel)+'/notifications/plan').json,before)
        response=self.request('POST',path,body)
        self.assertEqual(response.status_code,201,response.json)
        saved=response.json['vessel'];self.assertTrue(response.json['projection_applied'])
        self.assertEqual(saved['expiry_date'],preview.json['projection']['expiry_date'])
        self.assertEqual(saved['stage'],'ampliacion');self.assertEqual(saved['calculation_mode'],'calculated')
        self.assertEqual(saved['version'],vessel['version']+1)
        self.assertEqual(self.request('GET',path).json['movements'][0]['event_date'],'2026-11-17')
        plans=self.request('GET',self.path(vessel)+'/notifications/plan').json['plans']
        self.assertEqual(len([p for p in plans if p['status']=='planned']),9)
        self.assertTrue(all(p['status']=='cancelled' for p in plans if p['expiry_date']==vessel['expiry_date']))
        self.assertEqual({p['date'] for p in plans if p['status']=='planned'},{'2027-10-03','2027-10-18','2027-11-01'})
        self.assertEqual(self.request('POST',path,dict(body,version=saved['version'])).status_code,409)
        self.assertEqual(len(self.request('GET',path).json['movements']),1)
        with self.fixture_connection() as db:
            change=db.execute("SELECT after_state FROM servamar_test.v90_audit WHERE vessel_id=%s AND action='movement'",(vessel['id'],)).fetchone()[0]
            self.assertTrue(change['calculation_mode_changed'])
            self.assertEqual(db.execute('SELECT count(*) FROM servamar_test.v91_notification_events WHERE vessel_id=%s',(vessel['id'],)).fetchone()[0],0)

    def test_extension_conversion_rolls_back_on_audit_failure(self):
        vessel=self.create(start_date='04/11/2026')
        path=self.path(vessel)+'/movements'
        before=self.request('GET',self.path(vessel)+'/notifications/plan').json
        with patch('postgres_test_app.audit',side_effect=RuntimeError('fictional audit failure')):
            response=self.request('POST',path,dict(version=vessel['version'],kind='ampliacion',apply_calculation=True))
        self.assertEqual(response.status_code,503,response.json)
        self.assertEqual(self.request('GET',self.path(vessel)).json['vessel'],vessel)
        self.assertEqual(self.request('GET',path).json['movements'],[])
        self.assertEqual(self.request('GET',self.path(vessel)+'/notifications/plan').json,before)

    def test_edit_manual_extension_can_apply_calculation_and_undo(self):
        vessel=self.create(start_date='04/11/2026',expiry_date='')
        vessel,mid=self.add(vessel,'ampliacion','10/11/2026')
        self.assertIsNone(vessel['expiry_date'])
        path=self.path(vessel)+'/movements'
        body=dict(version=vessel['version'],movement_id=mid,kind='ampliacion',event_date='11/11/2026',apply_calculation=True)
        preview=self.request('POST',path+'/preview',body)
        self.assertEqual(preview.status_code,200,preview.json)
        response=self.request('PUT',path+'/'+str(mid),body)
        self.assertEqual(response.status_code,200,response.json);vessel=response.json['vessel']
        self.assertEqual(vessel['expiry_date'],preview.json['projection']['expiry_date'])
        self.assertEqual(len(self.request('GET',path).json['movements']),1)
        self.assertEqual(vessel['calculation_mode'],'calculated')
        response=self.request('DELETE',path+'/'+str(mid),dict(version=vessel['version'],confirm_declaration=vessel['declaration']))
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(response.json['vessel']['expiry_date'],'2027-02-02')
        self.assertEqual(response.json['vessel']['stage'],'ingreso')

    def test_preview_invalid_history_ownership_version_and_options(self):
        vessel=self.create(start_date='04/11/2026')
        path=self.path(vessel)+'/movements'
        body=dict(version=vessel['version'],kind='ampliacion',event_date='18/11/2026',apply_calculation=True)
        for suffix in ('/preview',''):
            self.assertEqual(self.request('POST',path+suffix,body).status_code,409)
            self.assertEqual(self.request('POST',path+suffix,dict(body,apply_calculation='true')).status_code,400)
            self.assertEqual(self.request('POST',path+suffix,dict(body,event_date='10/11/2026',version=100)).status_code,409)
        self.assertEqual(self.request('POST',path+'/preview',dict(body,movement_id=True)).status_code,400)
        self.assertEqual(self.request('POST',path+'/preview',dict(body,movement_id=999999)).status_code,404)
        self.assertEqual(self.request('GET',self.path(vessel)).json['vessel'],vessel)
        vessel,_=self.add(vessel,'ampliacion','12/12/2026')
        # Preserve historical rows for correction; never silently discard or re-date them.
        response=self.request('POST',path+'/preview',dict(body,version=vessel['version'],event_date='10/11/2026'))
        self.assertEqual(response.status_code,409,response.json)
        self.assertEqual(self.request('GET',self.path(vessel)).json['vessel'],vessel)


if __name__=='__main__':unittest.main()
