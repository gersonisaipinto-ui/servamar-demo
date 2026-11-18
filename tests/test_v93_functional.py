"""End-to-end modules on isolated PostgreSQL fixtures; no real vessels or delivery."""
import base64
import hashlib
import io
import os
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch
import test_v90_postgres_console as support
import postgres_test_app as target
from postgres_test_documents import validate_file, MAX_BYTES
from postgres_test_reports import xlsx_bytes, safe_cell


def png():
    from PIL import Image
    data=io.BytesIO();Image.new('RGB',(12,12),'blue').save(data,format='PNG');return data.getvalue()


class FileValidationTests(unittest.TestCase):
    def test_invalid_type_name_content_and_size(self):
        base=dict(filename='ficticio.png',content_base64=base64.b64encode(png()).decode(),fictional_confirmed=True)
        self.assertEqual(validate_file(base,target.ApiError)[1],'image/png')
        for change in ({'filename':''},{'filename':'document.html'},{'content_base64':'not valid'},
                       {'fictional_confirmed':False},{'content_base64':base64.b64encode(b'fake').decode()},
                       {'content_base64':'A'*(MAX_BYTES*2)}):
            with self.subTest(change=list(change)),self.assertRaises(target.ApiError):validate_file(dict(base,**change),target.ApiError)

    def test_xlsx_formula_and_xml_safety(self):
        from openpyxl import load_workbook
        workbook=load_workbook(io.BytesIO(xlsx_bytes([['=1+1','<test>','normal']+['']*4])))
        self.assertEqual(workbook.active['A1'].data_type,'s')
        self.assertEqual(workbook.active['B1'].value,'<test>')
        self.assertTrue(safe_cell('  =1+1').startswith("'"))


@unittest.skipUnless(os.getenv('V90_TEST_POSTGRES_URL'),'Requires isolated PostgreSQL')
class FunctionalTests(support.DatabaseTests):
    @classmethod
    def setUpClass(cls):
        import psycopg
        cls.url=os.environ['V90_TEST_POSTGRES_URL']
        cls.schema='v93_ci_'+uuid.uuid4().hex
        cls.migration='\n'.join(Path('migrations',name).read_text().replace('servamar_test',cls.schema)
                                for name in ('v90_test_console.sql','v91_test_foundation.sql','v93_functional_test.sql'))
        with psycopg.connect(cls.url) as db:
            db.execute('CREATE SCHEMA '+cls.schema)
            db.execute(support.FIXTURE.split('CREATE TABLE {s}.v91_vessel_contacts')[0].format(s=cls.schema))
            db.execute(cls.migration)
        cls.addClassCleanup(cls.cleanup_schema)

    @classmethod
    def cleanup_schema(cls):
        import psycopg
        if not cls.schema.startswith('v93_ci_'):raise RuntimeError('Unexpected fixture')
        with psycopg.connect(cls.url) as db:
            for name in ('v96_notification_schedule','v93_document_content','v90_audit','v91_notification_events','v91_documents','v91_vessel_contacts','alert_settings','history','vessels'):
                db.execute('DROP TABLE '+cls.schema+'.'+name)
            for name in ('v90_vessel_id_seq','v90_history_id_seq'):db.execute('DROP SEQUENCE '+cls.schema+'.'+name)
            db.execute('DROP SCHEMA '+cls.schema)

    def contact(self,vessel,name='Capitán Ejemplo',primary=True):
        response=self.request('POST',self.path(vessel)+'/contacts',dict(version=vessel['version'],contact_role='captain',full_name=name,email='captain@example.invalid',is_primary=primary))
        self.assertEqual(response.status_code,201,response.json);return response.json

    def document(self,vessel,content=None,filename='ficticio.png'):
        content=png() if content is None else content
        return self.request('POST',self.path(vessel)+'/documents',dict(version=vessel['version'],document_type='permiso_ingreso',filename=filename,content_base64=base64.b64encode(content).decode(),fictional_confirmed=True))

    def test_contacts_edit_primary_ownership_and_audit(self):
        vessel=self.create();first=self.contact(vessel);vessel=first['vessel']
        second=self.contact(vessel,'Otra Persona');vessel=second['vessel']
        contacts=self.request('GET',self.path(vessel)+'/contacts').json['contacts']
        self.assertEqual(sum(c['is_primary'] for c in contacts),1)
        body=dict(version=vessel['version'],contact_role='owner',full_name='Editado Ficticio',email='owner@example.invalid',is_primary=True)
        path=self.path(vessel)+'/contacts/'+str(first['id'])
        response=self.request('PUT',path,body);self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(self.request('PUT',path,body).status_code,409)
        other=self.create()
        self.assertEqual(self.request('PUT',self.path(other)+'/contacts/'+str(first['id']),dict(body,version=1)).status_code,404)
        vessel=response.json['vessel']
        with patch.object(target,'audit',side_effect=RuntimeError('test rollback')):
            self.assertEqual(self.request('DELETE',path,dict(version=vessel['version'])).status_code,503)
        self.assertEqual(len(self.request('GET',self.path(vessel)+'/contacts').json['contacts']),2)
        response=self.request('DELETE',path,dict(version=vessel['version']));self.assertEqual(response.status_code,200,response.json)
        with self.fixture_connection() as db:
            actions=[r[0] for r in db.execute('SELECT action FROM servamar_test.v90_audit WHERE vessel_id=%s ORDER BY id',(vessel['id'],)).fetchall()]
        self.assertIn('contact_edit',actions);self.assertIn('contact_delete',actions)

    def test_movement_edit_delete_audit_and_manual_expiry(self):
        vessel=self.create();expiry=vessel['expiry_date']
        response=self.request('POST',self.path(vessel)+'/movements',dict(version=1,kind='salida',event_date='18/11/2026'))
        self.assertEqual(response.status_code,201,response.json)
        vessel=response.json['vessel'];movement=response.json['id'];path=self.path(vessel)+'/movements/'+str(movement)
        data=dict(version=vessel['version'],kind='salida',event_date='19/11/2026',description='Corregido')
        response=self.request('PUT',path,data);self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(response.json['vessel']['expiry_date'],expiry);self.assertFalse(response.json['projection_applied'])
        self.assertEqual(self.request('PUT',path,data).status_code,409)
        vessel=response.json['vessel']
        self.assertEqual(self.request('PUT',path,dict(data,version=vessel['version'],event_date='16/11/2026')).status_code,400)
        other=self.create()
        self.assertEqual(self.request('PUT',self.path(other)+'/movements/'+str(movement),dict(data,version=1)).status_code,404)
        confirmation=dict(version=vessel['version'],confirm_declaration=vessel['declaration'])
        with patch.object(target,'audit',side_effect=RuntimeError('test rollback')):
            self.assertEqual(self.request('DELETE',path,confirmation).status_code,503)
        self.assertEqual(len(self.request('GET',self.path(vessel)+'/movements').json['movements']),1)
        self.assertEqual(self.request('DELETE',path,dict(confirmation,confirm_declaration='wrong')).status_code,400)
        self.assertEqual(self.request('DELETE',path,confirmation).status_code,200)
        with self.fixture_connection() as db:
            before=db.execute("SELECT before_state FROM servamar_test.v90_audit WHERE vessel_id=%s AND action='movement_delete'",(vessel['id'],)).fetchone()[0]
        self.assertEqual(before['description'],'Corregido')
        self.assertEqual(self.request('GET',self.path(vessel)).json['vessel']['expiry_date'],expiry)

    def test_documents_roundtrip_archive_ownership_and_rollback(self):
        vessel=self.create();body=png();response=self.document(vessel,body)
        self.assertEqual(response.status_code,201,response.json)
        document_id=response.json['id'];vessel=response.json['vessel'];path=self.path(vessel)+'/documents/'+str(document_id)
        response=self.request('GET',path+'/download');self.assertEqual(response.data,body)
        self.assertIn('attachment',response.headers['Content-Disposition'])
        self.assertEqual(self.document(vessel,body).status_code,409)
        other=self.create();self.assertEqual(self.request('GET',self.path(other)+'/documents/'+str(document_id)+'/download').status_code,404)
        self.assertEqual(self.request('PATCH',path,dict(version=1,archived=True)).status_code,409)
        response=self.request('PATCH',path,dict(version=vessel['version'],archived=True));self.assertEqual(response.status_code,200,response.json)
        vessel=response.json['vessel']
        self.assertTrue(self.request('GET',self.path(vessel)+'/documents').json['documents'][0]['archived_at'])
        response=self.request('PATCH',path,dict(version=vessel['version'],archived=False));self.assertEqual(response.status_code,200,response.json)
        with patch.object(target,'audit',side_effect=RuntimeError('test rollback')):
            failed=self.document(other,body)
            self.assertEqual(failed.status_code,503,failed.json)
        self.assertEqual(self.request('GET',self.path(other)+'/documents').json['documents'],[])
        with self.fixture_connection() as db:
            db.execute('UPDATE servamar_test.v93_document_content SET content=%s WHERE document_id=%s',(b'bad',document_id))
        self.assertEqual(self.request('GET',path+'/download').status_code,409)

    def test_pdf_and_jpeg_documents_and_no_false_send(self):
        from reportlab.pdfgen.canvas import Canvas
        from PIL import Image
        vessel=self.create();data=io.BytesIO();canvas=Canvas(data);canvas.drawString(20,20,'DOCUMENTO FICTICIO');canvas.save()
        response=self.document(vessel,data.getvalue(),'ficticio.pdf');self.assertEqual(response.status_code,201,response.json)
        vessel=response.json['vessel'];data=io.BytesIO();Image.new('RGB',(10,10),'red').save(data,format='JPEG')
        response=self.document(vessel,data.getvalue(),'ficticio.jpg');self.assertEqual(response.status_code,201,response.json)
        vessel=response.json['vessel'];path=self.path(vessel)+'/notifications'
        response=self.request('GET',path+'/preview');self.assertEqual(response.status_code,200,response.json)
        self.assertFalse(response.json['delivery_enabled']);self.assertIn('Hello',response.json['body']);self.assertIn('Hola',response.json['body'])
        with patch.dict(os.environ,SERVAMAR_NOTIFICATIONS_ENABLED='YES'):
            self.assertEqual(self.request('POST',path+'/send',dict(version=vessel['version'])).status_code,403)
        with self.fixture_connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM servamar_test.v91_notification_events WHERE vessel_id=%s',(vessel['id'],)).fetchone()[0],0)
        self.assertEqual(self.request('GET',self.path(vessel)).json['vessel']['version'],vessel['version'])

    def test_reports_filters_literal_search_formats_and_bounds(self):
        from openpyxl import load_workbook
        import pymupdf
        marker='report_'+uuid.uuid4().hex[:10]
        first=self.create(name=marker+' 100%',captain='=SUM(1,2)',registration_number='FICTICIO-REG',start_date='04/11/2026',expiry_date='02/02/2027')
        self.create(name=marker+' other',start_date='01/12/2026',expiry_date='04/03/2027')
        from urllib.parse import urlencode
        query=urlencode(dict(q=marker,date_field='start_date',month='2026-11',**{'from':'04/11/2026','to':'04/11/2026'}))
        response=self.request('GET','/api/test/search?'+query);self.assertEqual(response.status_code,200,response.json)
        self.assertEqual([r['id'] for r in response.json['vessels']],[first['id']])
        self.assertEqual(self.request('GET','/api/test/search?'+urlencode(dict(q=marker+' 100%'))).json['count'],1)
        for bad in ('date_field=invalid','from=31/11/2026','from=05/11/2026&to=04/11/2026','month=9999-12','stage=invalid'):
            self.assertEqual(self.request('GET','/api/test/search?'+bad).status_code,400)
        csv=self.request('GET','/api/test/export.csv?'+query);self.assertIn("'=SUM",csv.text);self.assertIn('04/11/2026',csv.text)
        excel=self.request('GET','/api/test/export.xlsx?'+query);self.assertEqual(excel.status_code,200)
        workbook=load_workbook(io.BytesIO(excel.data));self.assertEqual(workbook.active.max_row,2);self.assertEqual(workbook.active['C2'].data_type,'s')
        pdf=self.request('GET','/api/test/export.pdf?'+query);self.assertEqual(pdf.status_code,200)
        with pymupdf.open(stream=pdf.data,filetype='pdf') as document:
            self.assertIn('04/11/2026',''.join(page.get_text() for page in document))

    def test_report_limit_is_explicit_and_exports_never_silently_truncate(self):
        marker='BULK'+uuid.uuid4().hex[:8]
        with self.fixture_connection() as db:
            db.execute("INSERT INTO servamar_test.vessels(declaration,name,captain,stage) SELECT %s||g::text,%s,'Ficticio','ingreso' FROM generate_series(1,1001) g",('ST-TEST-'+marker+'-',marker))
        result=self.request('GET','/api/test/search?q='+marker);self.assertEqual(result.json['count'],1000);self.assertTrue(result.json['capped'])
        for format in ('csv','xlsx','pdf'):
            self.assertEqual(self.request('GET','/api/test/export.'+format+'?q='+marker).status_code,409)

    def test_new_routes_reject_unauthenticated_and_missing_csrf(self):
        for path in ('documents','notifications/preview'):
            self.assertEqual(self.client.get('/api/test/vessels/1/'+path).status_code,401)
        for method,path in (('POST','documents'),('PATCH','documents/1'),('PUT','movements/1'),('DELETE','movements/1'),('PUT','contacts/1'),('POST','notifications/send')):
            headers={k:v for k,v in self.headers.items() if k!='X-CSRF-Token'}
            self.assertEqual(self.client.open('/api/test/vessels/1/'+path,method=method,headers=headers,json={}).status_code,403)

if __name__=='__main__':unittest.main()
