"""Browser smoke test of the test console; APIs are intercepted with fictional data.
Run: python tests/ui_v93_smoke.py. PostgreSQL behavior is covered separately in CI.
"""
import base64
import json
import os
import sys
import threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright, expect
import postgres_test_app as target

os.environ.update(SERVAMAR_PG_TEST_MODE='YES',SERVAMAR_PG_TEST_PASSWORD='browser-fictional-password',
                  SERVAMAR_PG_TEST_BRANCH_ID=target.TEST_BRANCH,SERVAMAR_PG_TEST_DATABASE_URL='postgresql://invalid/test',
                  SERVAMAR_PG_TEST_REQUIRE_HTTPS='NO')
vessel=dict(id=1,declaration='ST-TEST-BROWSER',name='Velero ficticio',captain='Capitán de prueba',
            registration_number='REG-TEST',version=1,stage='ingreso',start_date='2026-11-04',expiry_date='2027-02-02')
movements=[dict(id=1,kind='salida',event_date='2026-11-17',expiry_date=None,description='Ficticio')]
contacts=[];documents=[];requests=[]

def intercept(route):
    from urllib.parse import urlsplit
    request=route.request;path=urlsplit(request.url).path;method=request.method
    requests.append((method,path));data=request.post_data_json if request.post_data else {}
    result={};status=200
    if path=='/api/test/vessels':result={'vessels':[vessel]}
    elif path=='/api/test/search':result=dict(vessels=[vessel],count=1,capped=False)
    elif path=='/api/test/expiring':result=dict(vessels=[])
    elif path=='/api/test/vessels/1':result=dict(vessel=vessel,dependencies=dict(movements=len(movements),alerts=0,contacts=0,documents=0,notifications=0))
    elif '/notifications/preview' in path:result=dict(subject='PRUEBA',body='Hello, Test\nHola, Prueba',warning='Sin envíos',reminders=[])
    elif path.endswith('/movements') and method=='GET':result=dict(movements=movements)
    elif '/movements/' in path and method=='PUT':
        movements[0].update({k:v for k,v in data.items() if k!='version'});vessel['version']+=1;result=dict(vessel=vessel,updated=True)
    elif path.endswith('/contacts') and method=='GET':result=dict(contacts=contacts)
    elif path.endswith('/documents') and method=='GET':result=dict(documents=documents)
    elif path.endswith('/documents') and method=='POST':
        vessel['version']+=1;documents.append(dict(id=1,filename=data['filename'],document_type=data['document_type'],archived_at=None,size_bytes=100));result=dict(vessel=vessel,created=True,id=1);status=201
    elif path.startswith('/api/test/export.'):
        route.fulfill(status=200,body='FICTICIO',content_type='application/octet-stream');return
    else:raise AssertionError((method,path))
    route.fulfill(status=status,body=json.dumps(result),content_type='application/json')

server=make_server('127.0.0.1',8793,target.app,threaded=True)
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
try:
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(executable_path=os.getenv('SERVAMAR_TEST_CHROMIUM'),headless=True,args=['--no-sandbox'])
        context=browser.new_context(http_credentials={'username':'servamar-test','password':'browser-fictional-password'},viewport={'width':390,'height':844},accept_downloads=True)
        page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.route('**/api/test/**',intercept)
        page.goto('http://127.0.0.1:8793')
        expect(page.locator('#search-count')).to_contain_text('1 resultados')
        page.get_by_role('button',name='Agregar embarcación',exact=True).click()
        expect(page.locator('#vessel-form [name=calculation_mode]')).to_have_value('calculated')
        expect(page.locator('#vessel-form [name=expiry_date]')).to_be_disabled()
        expect(page.locator('#vessel-form [name=start_date]')).to_have_attribute('required','')
        page.locator('#vessel-form [name=calculation_mode]').select_option('manual')
        expect(page.locator('#vessel-form [name=expiry_date]')).to_be_enabled()
        page.locator('#cancel-edit').click()
        page.get_by_role('button',name='Movimientos',exact=True).click()
        expect(page.locator('#last-movement')).to_contain_text('17/11/2026')
        page.get_by_role('button',name='Editar movimiento',exact=True).click()
        page.locator('#movement-form [name=description]').fill('Descripción editada ficticia')
        page.get_by_role('button',name='Guardar movimiento',exact=True).click()
        expect(page.locator('#movements')).to_contain_text('Descripción editada ficticia')
        page.locator('#document-form [name=document]').set_input_files({'name':'ficticio.pdf','mimeType':'application/pdf','buffer':b'%PDF-ficticio'})
        page.locator('#document-form [name=fictional_confirmed]').check()
        page.get_by_role('button',name='Guardar documento',exact=True).click()
        expect(page.locator('#documents')).to_contain_text('ficticio.pdf')
        page.get_by_role('button',name='Preparar vista previa',exact=True).click()
        expect(page.locator('#notification-body')).to_contain_text('Hello')
        with page.expect_download() as download:
            page.get_by_role('button',name='Excel',exact=True).click()
        assert download.value.suggested_filename=='servamar-pruebas.xlsx'
        page.get_by_role('button',name='Cerrar',exact=True).click()
        expect(page.locator('#document-section')).to_be_hidden();expect(page.locator('#notification-section')).to_be_hidden()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), 'Mobile overflow'
        page.set_viewport_size({'width':1440,'height':1000})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), 'Desktop overflow'
        assert not errors,errors
        assert ('PUT','/api/test/vessels/1/movements/1') in requests
        browser.close()
    print('PASS: mobile/desktop, movement edit, document upload, preview, Excel download; no JS errors')
finally:server.shutdown()
