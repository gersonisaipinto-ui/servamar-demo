"""V91: contacts API for the isolated fictional PostgreSQL test schema."""
import re
from flask import jsonify

ROLES = ('captain', 'owner', 'representative', 'other')


def register(app, protected, connection, get_vessel, check_version, audit, payload, text_field, ApiError):
    def read_contacts(db, vessel_id):
        rows = db.execute(
            'SELECT id,contact_role,full_name,email,phone,is_primary '
            'FROM servamar_test.v91_vessel_contacts WHERE vessel_id=%s ORDER BY is_primary DESC,id',
            (vessel_id,)).fetchall()
        keys = ('id', 'contact_role', 'full_name', 'email', 'phone', 'is_primary')
        return [dict(zip(keys, row)) for row in rows]

    @app.get('/api/test/vessels/<int:vessel_id>/contacts')
    @protected
    def list_contacts(vessel_id):
        with connection() as db:
            get_vessel(db, vessel_id)
            contacts = read_contacts(db, vessel_id)
        return jsonify(contacts=contacts)

    @app.post('/api/test/vessels/<int:vessel_id>/contacts')
    @protected
    def add_contact(vessel_id):
        data = payload()
        role = text_field(data, 'contact_role', 30)
        if role not in ROLES:
            raise ApiError('Tipo de contacto inválido')
        name = text_field(data, 'full_name', 200)
        email = text_field(data, 'email', 254, required=False)
        phone = text_field(data, 'phone', 60, required=False)
        if email and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
            raise ApiError('Correo electrónico inválido')
        primary = data.get('is_primary', False)
        if type(primary) is not bool:
            raise ApiError('Indicador principal inválido')
        with connection() as db:
            vessel = get_vessel(db, vessel_id, lock=True)
            check_version(data, vessel)
            if primary:
                db.execute('UPDATE servamar_test.v91_vessel_contacts SET is_primary=false WHERE vessel_id=%s', (vessel_id,))
            row = db.execute(
                'INSERT INTO servamar_test.v91_vessel_contacts '
                '(vessel_id,contact_role,full_name,email,phone,is_primary) '
                'VALUES (%s,%s,%s,%s,%s,%s) RETURNING id',
                (vessel_id, role, name, email or None, phone or None, primary)).fetchone()
            db.execute('UPDATE servamar_test.vessels SET version=version+1 WHERE id=%s', (vessel_id,))
            audit(db, vessel_id, 'contact_create', None,
                  dict(id=row[0], contact_role=role, full_name=name, email=email, phone=phone, is_primary=primary))
            vessel = get_vessel(db, vessel_id)
        return jsonify(created=True, id=row[0], vessel=vessel), 201

    @app.delete('/api/test/vessels/<int:vessel_id>/contacts/<int:contact_id>')
    @protected
    def remove_contact(vessel_id, contact_id):
        data = payload()
        with connection() as db:
            vessel = get_vessel(db, vessel_id, lock=True)
            check_version(data, vessel)
            row = db.execute('SELECT id,contact_role,full_name,email,phone,is_primary '
                             'FROM servamar_test.v91_vessel_contacts WHERE id=%s AND vessel_id=%s FOR UPDATE',
                             (contact_id, vessel_id)).fetchone()
            if not row:
                raise ApiError('Contacto inexistente', 404)
            before = dict(zip(('id','contact_role','full_name','email','phone','is_primary'), row))
            db.execute('DELETE FROM servamar_test.v91_vessel_contacts WHERE id=%s AND vessel_id=%s',
                       (contact_id, vessel_id))
            db.execute('UPDATE servamar_test.vessels SET version=version+1 WHERE id=%s', (vessel_id,))
            audit(db, vessel_id, 'contact_delete', before, None)
            vessel = get_vessel(db, vessel_id)
        return jsonify(deleted=True, vessel=vessel)
