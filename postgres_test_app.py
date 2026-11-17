"""SERVAMAR V93: independent fictional PostgreSQL console. Never imports app.py."""
import hashlib
import hmac
import os
import re
from datetime import date
from functools import wraps
from urllib.parse import urlsplit

from flask import Flask, Response, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

app = Flask(__name__, static_folder=None)
app.config['MAX_CONTENT_LENGTH'] = 3 * 1024 * 1024
TEST_BRANCH = 'br-green-band-arsmtoxc'
TEST_HOST = 'ep-spring-sunset-arxamsuy.c-4.us-west-2.aws.neon.tech'
KINDS = ('ingreso', 'ampliacion', 'deposito', 'salida', 'retorno', 'cierre')
FIELDS = ('id', 'declaration', 'name', 'captain', 'stage', 'start_date', 'expiry_date', 'version', 'registration_number')
SELECT_VESSEL = 'SELECT ' + ','.join(FIELDS) + ' FROM servamar_test.vessels'


def configured():
    return (os.getenv('SERVAMAR_PG_TEST_MODE') == 'YES'
            and len(os.getenv('SERVAMAR_PG_TEST_PASSWORD', '')) >= 16
            and bool(os.getenv('SERVAMAR_PG_TEST_DATABASE_URL'))
            and os.getenv('SERVAMAR_PG_TEST_BRANCH_ID') == TEST_BRANCH)


def authorized():
    auth = request.authorization
    return bool(auth and auth.type == 'basic'
                and hmac.compare_digest((auth.username or '').encode(),
                                        os.getenv('SERVAMAR_PG_TEST_USERNAME', 'servamar-test').encode())
                and hmac.compare_digest((auth.password or '').encode(),
                                        os.getenv('SERVAMAR_PG_TEST_PASSWORD', '').encode()))


def csrf_token():
    # Stable across workers; invalidated when the private password rotates.
    return hmac.new(os.environ['SERVAMAR_PG_TEST_PASSWORD'].encode(),
                    b'servamar-v90-csrf', hashlib.sha256).hexdigest()


class ApiError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def protected(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not configured():
            return jsonify(error='Consola de pruebas deshabilitada'), 503
        if not authorized():
            return Response('Authentication required', 401,
                            {'WWW-Authenticate': 'Basic realm="SERVAMAR TEST"'})
        if (os.getenv('SERVAMAR_PG_TEST_REQUIRE_HTTPS', 'YES') == 'YES'
                and request.headers.get('X-Forwarded-Proto', request.scheme).split(',')[0].strip() != 'https'):
            return jsonify(error='Se requiere HTTPS'), 403
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            origin = request.headers.get('Origin')
            if origin and origin != 'https://' + request.host:
                return jsonify(error='Origen no permitido'), 403
            token = request.headers.get('X-CSRF-Token', '')
            if not hmac.compare_digest(token.encode(), csrf_token().encode()):
                return jsonify(error='Recarga la página antes de guardar'), 403
            if not request.is_json:
                return jsonify(error='Se requiere un objeto JSON'), 415
        if request.endpoint != 'upload_document' and (request.content_length or 0) > 32 * 1024:
            return jsonify(error='Solicitud demasiado grande'), 413
        try:
            return fn(*args, **kwargs)
        except ApiError as exc:
            return jsonify(error=str(exc)), exc.status
        except HTTPException as exc:
            return jsonify(error='Solicitud inválida o demasiado grande'), exc.code
        except (ValueError, TypeError):
            return jsonify(error='Datos inválidos'), 400
        except Exception as exc:
            if getattr(exc, 'sqlstate', None) == '23505':
                return jsonify(error='Registro de prueba duplicado'), 409
            if getattr(exc, 'sqlstate', None) in ('23503', '23001'):
                return jsonify(error='No se puede eliminar: existen registros vinculados'), 409
            # Never expose connection strings, SQL parameters or driver errors.
            app.logger.error('PostgreSQL test request failed: %s', type(exc).__name__)
            return jsonify(error='No fue posible completar la operación; vuelve a intentarlo'), 503
    return wrapped


def connection():
    import psycopg
    url = os.environ['SERVAMAR_PG_TEST_DATABASE_URL']
    parsed = urlsplit(url)
    if (parsed.scheme not in ('postgres', 'postgresql')
            or parsed.hostname not in (TEST_HOST, TEST_HOST.replace('.c-4.', '-pooler.c-4.'))
            or parsed.path != '/servamar_demo'):
        raise RuntimeError('Unexpected test database target')
    db = psycopg.connect(url, connect_timeout=8, sslmode='require')
    try:
        # PgBouncer rejects these startup options. Keep limits transaction-local
        # so the pooled backend never leaks settings into the next request.
        db.execute("SET LOCAL statement_timeout = '10s'")
        db.execute("SET LOCAL lock_timeout = '5s'")
    except Exception:
        db.close()
        raise
    return db


def ensure_test_declaration(declaration):
    if not isinstance(declaration, str) or not re.fullmatch(r'ST-(?:DEMO|TEST)-[A-Z0-9-]{1,40}', declaration):
        raise ApiError('Solo se permiten registros ficticios ST-DEMO- o ST-TEST-')


def parse_date(value):
    """ISO remains supported for V89 API callers; the UI uses dd/mm/yyyy."""
    if value is None or value == '':
        return None
    if not isinstance(value, str):
        raise ApiError('Fecha inválida; utiliza dd/mm/yyyy')
    try:
        if re.fullmatch(r'\d{2}/\d{2}/\d{4}', value):
            day, month, year = map(int, value.split('/'))
            return date(year, month, day)
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            return date.fromisoformat(value)
    except ValueError:
        pass
    raise ApiError('Fecha inválida; utiliza dd/mm/yyyy')


def payload():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError('Se requiere un objeto JSON')
    return data


def text_field(data, field, limit, required=True):
    value = data.get(field, '')
    if not isinstance(value, str) or len(value.strip()) > limit or (required and not value.strip()):
        raise ApiError('Campo inválido: ' + field)
    return value.strip()


def vessel_data(data):
    declaration = text_field(data, 'declaration', 48).upper()
    ensure_test_declaration(declaration)
    name = text_field(data, 'name', 200)
    captain = text_field(data, 'captain', 200)
    start, expiry = parse_date(data.get('start_date')), parse_date(data.get('expiry_date'))
    if start and expiry and expiry < start:
        raise ApiError('Vencimiento anterior al ingreso')
    registration = text_field(data, 'registration_number', 100, required=False)
    return declaration, name, captain, start, expiry, registration


def as_vessel(row):
    return dict(zip(FIELDS, [x.isoformat() if isinstance(x, date) else x for x in row]))


def get_vessel(db, vessel_id, lock=False):
    row = db.execute(SELECT_VESSEL + ' WHERE id=%s' + (' FOR UPDATE' if lock else ''), (vessel_id,)).fetchone()
    if not row:
        raise ApiError('Embarcación inexistente', 404)
    ensure_test_declaration(row[1])
    return as_vessel(row)


def check_version(data, vessel):
    if type(data.get('version')) is not int or data['version'] < 1:
        raise ApiError('Versión del registro requerida')
    if data['version'] != vessel['version']:
        raise ApiError('El registro cambió. Recarga y revisa antes de guardar', 409)


def audit(db, vessel_id, action, before, after):
    from psycopg.types.json import Jsonb
    db.execute('INSERT INTO servamar_test.v90_audit(vessel_id,action,before_state,after_state,actor) '
               'VALUES (%s,%s,%s,%s,%s)',
               (vessel_id, action, Jsonb(before), Jsonb(after), request.authorization.username))


@app.after_request
def security_headers(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    return response


@app.get('/healthz')
def health():
    return jsonify(service='servamar-postgres-test', version='V93', calculations_enabled=False, notifications_enabled=False, configured=configured())


@app.get('/')
@protected
def home():
    return render_template('postgres_test.html', csrf=csrf_token())


@app.get('/test-assets/<asset>')
@protected
def asset_file(asset):
    from flask import send_from_directory
    if asset not in ('postgres-test.js', 'postgres-test.css'):
        raise ApiError('Archivo inexistente', 404)
    return send_from_directory('static', asset)


@app.get('/api/test/vessels')
@protected
def vessels():
    with connection() as db:
        rows = db.execute(SELECT_VESSEL + " WHERE declaration ~ '^ST-(DEMO|TEST)-' ORDER BY expiry_date NULLS LAST,id").fetchall()
    return jsonify(vessels=[as_vessel(row) for row in rows])


@app.post('/api/test/vessels')
@protected
def add_vessel():
    values = vessel_data(payload())
    with connection() as db:
        row = db.execute("INSERT INTO servamar_test.vessels(declaration,name,captain,stage,start_date,expiry_date,registration_number,validated,notes) "
                         "VALUES (%s,%s,%s,'ingreso',%s,%s,%s,FALSE,'DATOS FICTICIOS: PRUEBA GRATUITA') RETURNING id", values).fetchone()
        vessel = get_vessel(db, row[0])
        audit(db, row[0], 'create', None, vessel)
    return jsonify(id=row[0], created=True, vessel=vessel), 201


@app.get('/api/test/vessels/<int:vessel_id>')
@protected
def vessel_detail(vessel_id):
    with connection() as db:
        vessel = get_vessel(db, vessel_id)
        counts = db.execute('SELECT (SELECT count(*) FROM servamar_test.history WHERE vessel_id=%s),'
                            '(SELECT count(*) FROM servamar_test.alert_settings WHERE vessel_id=%s)',
                            (vessel_id, vessel_id)).fetchone()
        contacts_count = db.execute('SELECT count(*) FROM servamar_test.v91_vessel_contacts WHERE vessel_id=%s', (vessel_id,)).fetchone()[0]
        documents_count = db.execute('SELECT count(*) FROM servamar_test.v91_documents WHERE vessel_id=%s', (vessel_id,)).fetchone()[0]
        notifications_count = db.execute('SELECT count(*) FROM servamar_test.v91_notification_events WHERE vessel_id=%s', (vessel_id,)).fetchone()[0]
    return jsonify(vessel=vessel, dependencies=dict(movements=counts[0], alerts=counts[1], contacts=contacts_count, documents=documents_count, notifications=notifications_count))


@app.put('/api/test/vessels/<int:vessel_id>')
@protected
def edit_vessel(vessel_id):
    data = payload()
    values = vessel_data(data)
    with connection() as db:
        before = get_vessel(db, vessel_id, lock=True)
        check_version(data, before)
        if values[3]:
            earliest = db.execute('SELECT min(event_date) FROM servamar_test.history WHERE vessel_id=%s', (vessel_id,)).fetchone()[0]
            if earliest and values[3] > earliest:
                raise ApiError('El ingreso no puede ser posterior al historial de movimientos')
        db.execute('UPDATE servamar_test.vessels SET declaration=%s,name=%s,captain=%s,start_date=%s,expiry_date=%s,registration_number=%s,version=version+1 WHERE id=%s', (*values, vessel_id))
        vessel = get_vessel(db, vessel_id)
        audit(db, vessel_id, 'edit', before, vessel)
    return jsonify(vessel=vessel, updated=True)


@app.delete('/api/test/vessels/<int:vessel_id>')
@protected
def delete_vessel(vessel_id):
    data = payload()
    with connection() as db:
        vessel = get_vessel(db, vessel_id, lock=True)
        check_version(data, vessel)
        if data.get('confirm_declaration') != vessel['declaration']:
            raise ApiError('Escribe la matrícula exacta para confirmar la eliminación')
        counts = db.execute('SELECT (SELECT count(*) FROM servamar_test.history WHERE vessel_id=%s),'
                            '(SELECT count(*) FROM servamar_test.alert_settings WHERE vessel_id=%s)',
                            (vessel_id, vessel_id)).fetchone()
        if any(counts):
            raise ApiError('Eliminación bloqueada: existen movimientos o alertas vinculadas', 409)
        # The foreign keys remain RESTRICT; never delete child records here.
        db.execute('DELETE FROM servamar_test.vessels WHERE id=%s', (vessel_id,))
        audit(db, vessel_id, 'delete', vessel, None)
    return jsonify(deleted=True, id=vessel_id)


@app.get('/api/test/vessels/<int:vessel_id>/alerts')
@protected
def alerts(vessel_id):
    with connection() as db:
        get_vessel(db, vessel_id)
        rows = db.execute('SELECT days_before,enabled FROM servamar_test.alert_settings WHERE vessel_id=%s ORDER BY days_before DESC', (vessel_id,)).fetchall()
    return jsonify(alerts=[dict(days_before=r[0], enabled=r[1]) for r in rows])


@app.get('/api/test/vessels/<int:vessel_id>/movements')
@protected
def movements(vessel_id):
    with connection() as db:
        get_vessel(db, vessel_id)
        rows = db.execute('SELECT id,kind,event_date,expiry_date,description FROM servamar_test.history WHERE vessel_id=%s ORDER BY event_date NULLS LAST,id', (vessel_id,)).fetchall()
    keys = ('id', 'kind', 'event_date', 'expiry_date', 'description')
    return jsonify(movements=[dict(zip(keys, [v.isoformat() if isinstance(v, date) else v for v in row])) for row in rows])


@app.post('/api/test/vessels/<int:vessel_id>/movements')
@protected
def add_movement(vessel_id):
    data = payload()
    kind = text_field(data, 'kind', 30)
    if kind not in KINDS:
        raise ApiError('Tipo de movimiento inválido')
    event_date, expiry = parse_date(data.get('event_date')), parse_date(data.get('expiry_date'))
    if not event_date:
        raise ApiError('Fecha del movimiento requerida')
    if expiry and expiry < event_date:
        raise ApiError('Vencimiento anterior al movimiento')
    description = text_field(data, 'description', 2000, required=False)
    with connection() as db:
        vessel = get_vessel(db, vessel_id, lock=True)
        check_version(data, vessel)
        if vessel['start_date'] and event_date < date.fromisoformat(vessel['start_date']):
            raise ApiError('Movimiento anterior al ingreso')
        row = db.execute('INSERT INTO servamar_test.history(vessel_id,kind,event_date,expiry_date,description,created_at) '
                         'VALUES (%s,%s,%s,%s,%s,CURRENT_TIMESTAMP::text) RETURNING id',
                         (vessel_id, kind, event_date, expiry, description)).fetchone()
        # Record events only: no unvalidated permit calculations or stage changes.
        db.execute('UPDATE servamar_test.vessels SET version=version+1 WHERE id=%s', (vessel_id,))
        audit(db, vessel_id, 'movement', None, dict(id=row[0], kind=kind, event_date=event_date.isoformat(),
                                                 expiry_date=expiry.isoformat() if expiry else None, description=description))
        updated = get_vessel(db, vessel_id)
    return jsonify(id=row[0], created=True, vessel=updated), 201


from postgres_test_contacts import register as register_contacts
register_contacts(app, protected, lambda: connection(), get_vessel, check_version, lambda *args: audit(*args), payload, text_field, ApiError)

from postgres_test_reports import register as register_reports
register_reports(app, protected, lambda: connection(), ApiError)

from postgres_test_movements import register as register_movements
register_movements(app, protected, lambda: connection(), get_vessel, check_version,
                   lambda *args: audit(*args), payload, text_field, parse_date, KINDS, ApiError)
from postgres_test_documents import register as register_documents
register_documents(app, protected, lambda: connection(), get_vessel, check_version,
                   lambda *args: audit(*args), payload, text_field, ApiError)
from postgres_test_notifications import register as register_notifications
register_notifications(app, protected, lambda: connection(), get_vessel, ApiError)

if __name__ == '__main__':
    if not configured():
        raise SystemExit('Test configuration incomplete')
    app.run(host='127.0.0.1', port=int(os.getenv('PORT', '8790')), debug=False)
