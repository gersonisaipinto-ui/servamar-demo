"""Editable fictional history. Permit projection deliberately remains disabled."""
from datetime import date
from flask import jsonify


def register(app, protected, connection, get_vessel, check_version, audit, payload,
             text_field, parse_date, kinds, ApiError):
    def record(db, vessel_id, movement_id):
        row = db.execute('SELECT id,kind,event_date,expiry_date,description FROM servamar_test.history '
                         'WHERE vessel_id=%s AND id=%s FOR UPDATE', (vessel_id, movement_id)).fetchone()
        if not row:
            raise ApiError('Movimiento inexistente', 404)
        return dict(zip(('id','kind','event_date','expiry_date','description'),
                        [v.isoformat() if isinstance(v, date) else v for v in row]))

    @app.put('/api/test/vessels/<int:vessel_id>/movements/<int:movement_id>')
    @protected
    def edit_movement(vessel_id, movement_id):
        data = payload()
        kind = text_field(data, 'kind', 30)
        event = parse_date(data.get('event_date'))
        expiry = parse_date(data.get('expiry_date'))
        description = text_field(data, 'description', 2000, required=False)
        if kind not in kinds or not event:
            raise ApiError('Tipo y fecha válidos del movimiento requeridos')
        if expiry and expiry < event:
            raise ApiError('Vencimiento anterior al movimiento')
        with connection() as db:
            vessel = get_vessel(db, vessel_id, lock=True)
            check_version(data, vessel)
            before = record(db, vessel_id, movement_id)
            if vessel['start_date'] and event < date.fromisoformat(vessel['start_date']):
                raise ApiError('Movimiento anterior al ingreso')
            db.execute('UPDATE servamar_test.history SET kind=%s,event_date=%s,expiry_date=%s,description=%s '
                       'WHERE vessel_id=%s AND id=%s', (kind,event,expiry,description,vessel_id,movement_id))
            db.execute('UPDATE servamar_test.vessels SET version=version+1 WHERE id=%s', (vessel_id,))
            after = record(db, vessel_id, movement_id)
            audit(db, vessel_id, 'movement_edit', before, after)
            vessel = get_vessel(db, vessel_id)
        return jsonify(updated=True, movement=after, vessel=vessel, projection_applied=False)

    @app.delete('/api/test/vessels/<int:vessel_id>/movements/<int:movement_id>')
    @protected
    def delete_movement(vessel_id, movement_id):
        data = payload()
        with connection() as db:
            vessel = get_vessel(db, vessel_id, lock=True)
            check_version(data, vessel)
            if data.get('confirm_declaration') != vessel['declaration']:
                raise ApiError('Confirma la matrícula ficticia para eliminar el movimiento')
            before = record(db, vessel_id, movement_id)
            db.execute('DELETE FROM servamar_test.history WHERE vessel_id=%s AND id=%s', (vessel_id,movement_id))
            db.execute('UPDATE servamar_test.vessels SET version=version+1 WHERE id=%s', (vessel_id,))
            audit(db, vessel_id, 'movement_delete', before, None)
            vessel = get_vessel(db, vessel_id)
        return jsonify(deleted=True, vessel=vessel, projection_applied=False)
