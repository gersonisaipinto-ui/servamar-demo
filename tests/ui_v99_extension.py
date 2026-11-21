"""Real browser -> Flask -> ephemeral PostgreSQL; no intercepted API responses."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import postgres_test_app as target
from test_v90_postgres_console import PASSWORD
from test_v94_permits import CalculatedDatabaseTests

if not os.getenv('V90_TEST_POSTGRES_URL'):
    raise SystemExit('This test requires the isolated CI PostgreSQL database')

CalculatedDatabaseTests.setUpClass()
fixture = CalculatedDatabaseTests('runTest')
fixture.setUp()
server = None
try:
    vessel = fixture.create(name='Velero ficticio integración V99', start_date='04/11/2026', expiry_date='04/02/2027')
    api_path = fixture.path(vessel)
    artifacts = Path('artifacts/ui'); artifacts.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        cert, key = str(Path(tmp)/'cert.pem'), str(Path(tmp)/'key.pem')
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',key,
                        '-out',cert,'-days','1','-subj','/CN=localhost'],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        server = make_server('127.0.0.1', 8799, target.app, threaded=True, ssl_context=(cert,key))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=['--no-sandbox'])
            context = browser.new_context(ignore_https_errors=True,
                http_credentials={'username':'servamar-test','password':PASSWORD},
                viewport={'width':390,'height':844})
            page = context.new_page(); errors=[]; sends=[]
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: sends.append(request.url) if '/notifications/send' in request.url else None)

            def open_record():
                page.locator('.tabs [data-view=buscar]').click()
                page.locator('#records-section summary').click()
                page.locator('#rows tr').filter(has_text=vessel['name']).get_by_role('button', name='Movimientos', exact=True).click()
                expect(page.locator('#detail-name')).to_contain_text(vessel['name'])

            page.goto('https://127.0.0.1:8799'); open_record()
            expect(page.locator('#movement-calculation-option')).to_be_visible()
            expect(page.locator('#movement-form [name=apply_calculation]')).to_be_checked()
            expect(page.locator('#movement-calculated-expiry')).to_have_value('02/11/2027')
            expect(page.locator('#movement-preview')).to_contain_text('02/02/2027 + 9 meses calendario = 02/11/2027')
            expect(page.locator('#movement-preview')).to_contain_text('17/11/2026')
            expect(page.locator('#movement-preview')).to_contain_text('se activará el cálculo')
            assert fixture.request('GET',api_path).json['vessel']==vessel
            assert fixture.request('GET',api_path+'/movements').json['movements']==[]
            page.get_by_label('Calendario: Fecha del movimiento', exact=True).fill('2026-11-10')
            expect(page.locator('#movement-preview')).to_contain_text('10/11/2026')
            for width in (390,1440):
                page.set_viewport_size({'width':width,'height':1000})
                page.locator('#movement-form').scroll_into_view_if_needed()
                page.screenshot(path=str(artifacts/f'v99-extension-preview-{width}.png'), full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.set_viewport_size({'width':390,'height':844})
            save = page.get_by_role('button', name='Guardar movimiento', exact=True)
            save.click()
            expect(page.locator('#message')).to_contain_text('Movimiento guardado. Vencimiento: 02/11/2027')
            expect(page.locator('#permit-summary')).to_contain_text('02/11/2027')
            expect(save).to_be_enabled()
            expect(page.locator('#notification-plan')).to_contain_text('03/10/2027 · 30 días antes')
            saved=fixture.request('GET',api_path).json['vessel']
            assert saved['stage']=='ampliacion' and saved['calculation_mode']=='calculated'
            assert saved['expiry_date']=='2027-11-02'
            assert len(fixture.request('GET',api_path+'/movements').json['movements'])==1
            page.reload(); open_record()
            expect(page.locator('#permit-summary')).to_contain_text('02/11/2027')
            expect(page.locator('#last-movement')).to_contain_text('Ampliación')

            # Duplicate extension must explain the problem beside the form and roll back.
            page.locator('#movement-form [name=kind]').select_option('ampliacion')
            expect(page.locator('#movement-feedback')).to_contain_text('ya fue registrada')
            save.click()
            expect(save).to_be_enabled()
            expect(page.locator('#movement-feedback')).to_contain_text('ya fue registrada')
            assert fixture.request('GET',api_path).json['vessel']==saved
            assert len(fixture.request('GET',api_path+'/movements').json['movements'])==1

            page.locator('#movement-form [name=kind]').select_option('deposito')
            page.locator('#movement-form [name=event_date]').fill('17112026')
            expect(page.locator('#movement-calculated-expiry')).to_have_value('17/11/2027')
            save.click()
            expect(page.locator('#last-movement')).to_contain_text('Depósito')
            expect(save).to_be_enabled()
            expect(page.locator('#permit-summary')).to_contain_text('17/11/2027')
            expect(page.locator('#notification-plan')).to_contain_text('18/10/2027 · 30 días antes')
            plan=fixture.request('GET',api_path+'/notifications/plan').json
            assert not plan['delivery_enabled']
            assert all(p['status']=='cancelled' for p in plan['plans'] if p['expiry_date']=='2027-11-02')
            assert len([p for p in plan['plans'] if p['status']=='planned'])==9
            with fixture.fixture_connection() as db:
                assert db.execute('SELECT count(*) FROM servamar_test.v91_notification_events WHERE vessel_id=%s',(vessel['id'],)).fetchone()[0]==0
            assert not errors,errors
            assert not sends,sends
            page.screenshot(path=str(artifacts/'v99-extension-deposit-saved-mobile.png'), full_page=True)
            # Late authorization must start at the expiry adjusted by 37 days outside.
            vessel=fixture.create(name='Velero ficticio ampliación tardía V100',start_date='17/08/2026',expiry_date='22/12/2026')
            vessel,_=fixture.add(vessel,'salida','20/08/2026')
            vessel,_=fixture.add(vessel,'retorno','26/09/2026')
            api_path=fixture.path(vessel)
            page.reload();open_record()
            page.locator('#movement-form [name=kind]').select_option('ampliacion')
            page.locator('#movement-form [name=event_date]').fill('15012027')
            expect(page.locator('#movement-calculated-expiry')).to_have_value('22/09/2027')
            expect(page.locator('#movement-preview')).to_contain_text('22/12/2026 + 9 meses calendario = 22/09/2027')
            expect(page.locator('#movement-preview')).to_contain_text('37 días añadidos por retornos')
            expect(page.locator('#movement-preview')).to_contain_text('Autorización 24 días después')
            expect(page.locator('#movement-preview')).to_contain_text('Fecha de autorización futura')
            save.click()
            expect(page.locator('#permit-summary')).to_contain_text('22/09/2027')
            expect(save).to_be_enabled()
            expect(page.locator('#extension-basis')).to_contain_text('22/12/2026 + 9 meses calendario = 22/09/2027')
            expect(page.locator('#extension-basis')).to_contain_text('37 días añadidos por retornos')
            expect(page.locator('#notification-plan')).to_contain_text('23/08/2027 · 30 días antes')
            page.reload();open_record()
            expect(page.locator('#extension-basis')).to_contain_text('15/01/2027')
            expect(page.locator('#permit-summary')).to_contain_text('22/09/2027')
            for width in (390,1440):
                page.set_viewport_size({'width':width,'height':1000})
                page.screenshot(path=str(artifacts/f'v100-late-extension-{width}.png'),full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            saved=fixture.request('GET',api_path).json['vessel']
            assert saved['extension']['base_expiry_date']=='2026-12-22'
            assert saved['expiry_date']=='2027-09-22'
            plan=fixture.request('GET',api_path+'/notifications/plan').json
            assert all(p['status']=='cancelled' for p in plan['plans'] if p['expiry_date']=='2026-12-22')
            assert len([p for p in plan['plans'] if p['status']=='planned'])==9
            assert not errors,errors
            assert not sends,sends
            browser.close()
    print('PASS V100: late authorization after 37 days outside, visible start/date distinction, persistence and rescheduling; V99: real PostgreSQL browser extension save, manual conversion, optional authorization date, calculation preview, reload persistence, duplicate rollback, deposit and 30/15/1 rescheduling; no sends')
finally:
    if server: server.shutdown()
    fixture.doCleanups()
    CalculatedDatabaseTests.doClassCleanups()
