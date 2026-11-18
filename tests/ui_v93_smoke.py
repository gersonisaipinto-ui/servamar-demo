"""Browser smoke test of the test console; APIs are intercepted with fictional data.
Run: python tests/ui_v93_smoke.py. PostgreSQL behavior is covered separately in CI.
"""
import json
import os
import sys
import threading
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright, expect
import postgres_test_app as target

os.environ.update(SERVAMAR_PG_TEST_MODE='YES',SERVAMAR_PG_TEST_PASSWORD='browser-fictional-password',
                  SERVAMAR_PG_TEST_BRANCH_ID=target.TEST_BRANCH,SERVAMAR_PG_TEST_DATABASE_URL='postgresql://invalid/test',
                  SERVAMAR_PG_TEST_REQUIRE_HTTPS='NO')
vessel=dict(id=1,declaration='ST-TEST-BROWSER',name='Velero ficticio',captain='Capitán de prueba',
            registration_number='REG-TEST',version=1,stage='ingreso',calculation_mode='calculated',
            start_date='2026-11-04',expiry_date='2027-02-02',days_remaining=30)
movements=[dict(id=1,kind='salida',event_date='2026-11-17',expiry_date=None,description='Ficticio')]
contacts=[];documents=[];requests=[];queries=[]
def plans_for(expiry,status='planned'):
    return [dict(expiry_date=expiry,days_before=d,date=(date.fromisoformat(expiry)-timedelta(days=d)).isoformat(),channel=c,status=status)
            for d in (30,15,1) for c in ('email','push','windows')]
plans=plans_for(vessel['expiry_date'])+plans_for('2027-01-01','cancelled')
plans.append(dict(expiry_date='2026-11-01',days_before=30,date='2026-10-02',channel='email',status='sent'))
plans.append(dict(expiry_date='2026-11-01',days_before=15,date='2026-10-17',channel='push',status='elapsed'))

def intercept(route):
    from urllib.parse import urlsplit, parse_qs
    request=route.request;path=urlsplit(request.url).path;method=request.method
    requests.append((method,path));data=request.post_data_json if request.post_data else {}
    result={};status=200
    if path=='/api/test/vessels':result={'vessels':[vessel]}
    elif path=='/api/test/search':
        queries.append(parse_qs(urlsplit(request.url).query));result=dict(vessels=[vessel],count=1,capped=False)
    elif path=='/api/test/expiring':result=dict(vessels=[vessel])
    elif path=='/api/test/vessels/1':result=dict(vessel=vessel,dependencies=dict(movements=len(movements),alerts=0,contacts=0,documents=0,notifications=0))
    elif '/notifications/plan' in path:result=dict(expiry_date=vessel['expiry_date'],plans=plans,capped=True,delivery_enabled=False)
    elif '/notifications/preview' in path:result=dict(subject='PRUEBA',body='Hello, Test\nHola, Prueba',warning='Sin envíos',reminders=[])
    elif path.endswith('/movements') and method=='GET':result=dict(movements=movements)
    elif '/movements/' in path and method=='PUT':
        for key in ('event_date','expiry_date'):
            if data.get(key) and '/' in data[key]:data[key]='-'.join(reversed(data[key].split('/')))
        movements[0].update({k:v for k,v in data.items() if k!='version'});vessel['version']+=1
        if data['kind']=='ampliacion':
            for plan in plans:
                if plan['status']=='planned':plan['status']='cancelled'
            vessel.update(stage='ampliacion',expiry_date='2027-11-02')
            plans.extend(plans_for(vessel['expiry_date']))
        result=dict(vessel=vessel,updated=True)
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
        expect(page.locator('#expiring-results')).to_contain_text('Velero ficticio')
        expect(page.locator('#expiring-results')).to_contain_text('Capitán de prueba')
        expect(page.locator('#rows')).to_be_hidden()
        expect(page.locator('#search-results .card')).to_have_count(0)
        assert not queries, 'Initial screen should only show upcoming deadlines'
        page.locator('#search-form [name=stage]').select_option('ampliacion')
        date_from=page.locator('#search-form [name=from]')
        date_from.press_sequentially('01112026')
        expect(date_from).to_have_value('01/11/2026')
        expect(page.get_by_role('textbox',name='Desde',exact=True)).to_have_value('01/11/2026')
        expect(page.get_by_label('Calendario: Desde',exact=True)).to_have_value('2026-11-01')
        page.get_by_label('Calendario: Hasta',exact=True).fill('2027-11-30')
        expect(page.locator('#search-form [name=to]')).to_have_value('30/11/2027')
        page.get_by_role('button',name='Buscar',exact=True).click()
        expect(page.locator('#search-count')).to_contain_text('1 resultados')
        assert queries[-1]['stage']==['ampliacion'] and queries[-1]['from']==['01/11/2026'] and queries[-1]['to']==['30/11/2027'],queries
        page.locator('#clear-search').click()
        expect(page.locator('#search-results .card')).to_have_count(0)
        expect(page.get_by_label('Calendario: Desde',exact=True)).to_have_value('')
        page.get_by_role('button',name='Agregar embarcación',exact=True).click()
        expect(page.locator('#vessel-form [name=calculation_mode]')).to_have_value('calculated')
        expect(page.locator('#vessel-form [name=expiry_date]')).to_be_disabled()
        expect(page.get_by_label('Calendario: Vencimiento manual',exact=True)).to_be_disabled()
        entry=page.locator('#vessel-form [name=start_date]')
        entry.fill('29022024')
        expect(entry).to_have_value('29/02/2024')
        expect(page.get_by_label('Calendario: Fecha de ingreso',exact=True)).to_have_value('2024-02-29')
        entry.fill('31022026')
        assert not entry.evaluate('(el)=>el.checkValidity()'), 'Impossible dates must be rejected'
        entry.fill('2026-11-18')
        expect(entry).to_have_value('18/11/2026')
        entry.press('End');entry.press('Backspace')
        expect(entry).to_have_value('18/11/202')
        entry.press_sequentially('6')
        expect(entry).to_have_value('18/11/2026')
        assert entry.evaluate('(el)=>el.checkValidity()')
        expect(page.locator('#vessel-form [name=start_date]')).to_have_attribute('required','')
        page.locator('#vessel-form [name=calculation_mode]').select_option('manual')
        expect(page.locator('#vessel-form [name=expiry_date]')).to_be_enabled()
        expect(page.get_by_label('Calendario: Vencimiento manual',exact=True)).to_be_enabled()
        page.locator('#cancel-edit').click()
        page.get_by_role('button',name='Ver expediente',exact=True).click()
        expect(page.locator('#notification-plan .card')).to_have_count(3)
        expect(page.locator('#notification-plan')).to_contain_text('03/01/2027 · 30 días antes')
        expect(page.locator('#notification-plan')).to_contain_text('Correo · Android / push · Windows')
        expect(page.locator('#notification-history-rows')).to_be_hidden()
        page.locator('#notification-history summary').click()
        expect(page.locator('#notification-history-rows')).to_contain_text('Cancelado')
        expect(page.locator('#notification-history-rows')).to_contain_text('Ya enviado')
        expect(page.locator('#notification-history-rows')).to_contain_text('Fecha pasada')
        expect(page.locator('#notification-plan-limit')).to_be_visible()
        expect(page.locator('#last-movement')).to_contain_text('17/11/2026')
        page.get_by_role('button',name='Editar movimiento',exact=True).click()
        expect(page.get_by_label('Calendario: Fecha del movimiento',exact=True)).to_have_value('2026-11-17')
        expect(page.get_by_label('Calendario: Vencimiento de referencia (opcional)',exact=True)).to_be_disabled()
        page.locator('#movement-form [name=description]').fill('Descripción editada ficticia')
        page.get_by_role('button',name='Guardar movimiento',exact=True).click()
        expect(page.locator('#movements')).to_contain_text('Descripción editada ficticia')
        page.get_by_role('button',name='Editar movimiento',exact=True).click()
        page.locator('#movement-form [name=kind]').select_option('ampliacion')
        page.get_by_role('button',name='Guardar movimiento',exact=True).click()
        expect(page.locator('#last-movement')).to_contain_text('Ampliación')
        expect(page.get_by_role('button',name='Guardar movimiento',exact=True)).to_be_enabled()
        expect(page.locator('#automatic-notification-status')).to_contain_text('siguen el vencimiento actual: 02/11/2027')
        expect(page.locator('#notification-plan .card')).to_have_count(3)
        expect(page.locator('#notification-plan')).to_contain_text('03/10/2027 · 30 días antes')
        expect(page.locator('#notification-history-rows')).to_contain_text('Vencimiento: 02/02/2027')
        expect(page.locator('#notification-history-rows .planned')).to_have_count(0)
        expect(page.get_by_label('Calendario: Fecha del movimiento',exact=True)).to_have_value('')
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
        page.locator('#records-section summary').click()
        expect(page.locator('#rows')).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), 'Mobile overflow'
        page.set_viewport_size({'width':1440,'height':1000})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), 'Desktop overflow'
        assert not errors,errors
        assert not any('/notifications/send' in path for method,path in requests), 'Browser must never send notices'
        assert ('PUT','/api/test/vessels/1/movements/1') in requests
        browser.close()
    print('PASS: mobile/desktop, 30-day homepage, explicit search/stage filter, date typing/calendar/reset/validation, current/cancelled/sent/elapsed notice plans, movement edit, document upload, preview, Excel download; no JS errors or sends')
finally:server.shutdown()
