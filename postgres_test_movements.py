"""Editable fictional history. Calculated records replay atomically after each correction."""
from datetime import date
from flask import jsonify
import postgres_test_permits as permits


def register(app, protected, connection, get_vessel, check_version, audit, payload,
             text_field, parse_date, kinds, ApiError, recalculate):
    def values(data):
        kind = text_field(data, 'kind', 30)
        event = parse_date(data.get('event_date'))
        # The former console allowed an optional authorization date for extensions.
        # Make the effective date explicit in the preview and persist that same rule.
        if kind == 'ampliacion' and not event:
            event = permits.today_guatemala()
        expiry = parse_date(data.get('expiry_date'))
        description = text_field(data, 'description', 2000, required=False)
        if kind not in kinds or not event:
            raise ApiError('Tipo y fecha válidos del movimiento requeridos')
        if expiry and expiry < event:
            raise ApiError('Vencimiento anterior al movimiento')
        if type(data.get('apply_calculation', False)) is not bool:
            raise ApiError('Opción de cálculo inválida')
        return dict(kind=kind, event_date=event, expiry_date=expiry, description=description)

    def projection(db, vessel, data, movement, movement_id=None):
        if vessel['start_date'] and movement['event_date'] < permits.as_date(vessel['start_date']):
            raise ApiError('Movimiento anterior al ingreso')
        if vessel['calculation_mode'] != 'calculated' and not data.get('apply_calculation', False):
            return None
        history = permits.history_for(db, [vessel['id']]).get(vessel['id'], [])
        candidate = dict(movement, id=movement_id if movement_id is not None else max((m['id'] for m in history), default=0)+1)
        history = [m for m in history if m['id'] != movement_id] + [candidate]
        try:
            result = permits.calculate(vessel['start_date'], history)
            ordered = sorted(history, key=lambda m: (permits.as_date(m['event_date']), m['id']))
            prior = ordered[:ordered.index(candidate)]
            at_event = permits.calculate(vessel['start_date'], prior+[candidate], movement['event_date'])
            event = movement['event_date']; kind = movement['kind']
            formatted = lambda value: permits.as_date(value).strftime('%d/%m/%Y')
            if kind == 'ampliacion':
                extension = at_event['extension']
                base = extension['base_expiry_date']
                explanation = f'{formatted(base)} + 9 meses calendario = {formatted(at_event["expiry_date"])}.'
                explanation += f' El inicio toma el último vencimiento, incluidos {extension["days_added_before_extension"]} días añadidos por retornos.'
                if extension['late_days']:
                    explanation += f' Autorización {extension["late_days"]} días después: conserva ese inicio.'
                if event > permits.today_guatemala():
                    explanation += ' Fecha de autorización futura registrada en pruebas.'
            elif kind in ('ingreso', 'deposito'):
                term = '90 días' if kind == 'ingreso' else '12 meses calendario'
                explanation = f'{formatted(event)} + {term} = {formatted(at_event["expiry_date"])}.'
            elif kind == 'retorno':
                explanation = 'El retorno hasta el día 90 inclusive conserva el permiso y suma los días fuera al vencimiento.'
            else:
                explanation = at_event['plazo']
            if at_event['expiry_date'] != result['expiry_date']:
                explanation += ' El historial posterior deja el vencimiento vigente en '+formatted(result['expiry_date'])+'.'
            return dict(result, explanation=explanation)
        except (permits.PermitError, ValueError, OverflowError) as exc:
            raise ApiError(str(exc), 409)

    def apply_mode(db, vessel, projected):
        changed = bool(projected and vessel['calculation_mode'] != 'calculated')
        if changed:
            db.execute("UPDATE servamar_test.vessels SET calculation_mode='calculated' WHERE id=%s", (vessel['id'],))
        return changed

    @app.post('/api/test/vessels/<int:vessel_id>/movements/preview')
    @protected
    def preview_movement(vessel_id):
        data = payload(); movement = values(data)
        movement_id = data.get('movement_id')
        if movement_id is not None and (type(movement_id) is not int or movement_id < 1):
            raise ApiError('Movimiento inválido')
        with connection() as db:
            # Keep vessel, version and history coherent with all write endpoints.
            vessel = get_vessel(db, vessel_id, lock=True)
            check_version(data, vessel)
            if movement_id is not None:
                record(db, vessel_id, movement_id)
            projected = projection(db, vessel, data, movement, movement_id)
        return jsonify(projection=projected, effective_event_date=movement['event_date'].isoformat(),
                       previous_expiry_date=vessel['expiry_date'],
                       mode_will_change=bool(projected and vessel['calculation_mode'] != 'calculated'),
                       delivery_enabled=False)

    @app.post('/api/test/vessels/<int:vessel_id>/movements')
    @protected
    def add_movement(vessel_id):
        data = payload(); movement = values(data)
        with connection() as db:
            vessel = get_vessel(db, vessel_id, lock=True)
            check_version(data, vessel)
            projected = projection(db, vessel, data, movement)
            changed = apply_mode(db, vessel, projected)
            row = db.execute('INSERT INTO servamar_test.history(vessel_id,kind,event_date,expiry_date,description,created_at) '
                             'VALUES (%s,%s,%s,%s,%s,CURRENT_TIMESTAMP::text) RETURNING id',
                             (vessel_id, movement['kind'], movement['event_date'], movement['expiry_date'], movement['description'])).fetchone()
            automatic = recalculate(db, vessel_id)
            db.execute('UPDATE servamar_test.vessels SET version=version+1 WHERE id=%s', (vessel_id,))
            audit(db, vessel_id, 'movement', None, dict(id=row[0], **serialized(movement),
                  automatic_notices=automatic, calculation_mode_changed=changed))
            updated = get_vessel(db, vessel_id)
        return jsonify(id=row[0], created=True, vessel=updated, projection_applied=bool(projected)), 201

    def serialized(movement):
        return {k: v.isoformat() if isinstance(v, date) else v for k, v in movement.items()}

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
        movement = values(data)
        with connection() as db:
            vessel = get_vessel(db, vessel_id, lock=True)
            check_version(data, vessel)
            before = record(db, vessel_id, movement_id)
            projected = projection(db, vessel, data, movement, movement_id)
            changed = apply_mode(db, vessel, projected)
            db.execute('UPDATE servamar_test.history SET kind=%s,event_date=%s,expiry_date=%s,description=%s '
                       'WHERE vessel_id=%s AND id=%s', (*movement.values(),vessel_id,movement_id))
            automatic=recalculate(db, vessel_id)
            db.execute('UPDATE servamar_test.vessels SET version=version+1 WHERE id=%s', (vessel_id,))
            after = record(db, vessel_id, movement_id)
            audit(db, vessel_id, 'movement_edit', before, dict(after,automatic_notices=automatic,calculation_mode_changed=changed))
            vessel = get_vessel(db, vessel_id)
        return jsonify(updated=True, movement=after, vessel=vessel, projection_applied=vessel.get('calculation_mode') == 'calculated')

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
            recalculate(db, vessel_id)
            db.execute('UPDATE servamar_test.vessels SET version=version+1 WHERE id=%s', (vessel_id,))
            audit(db, vessel_id, 'movement_delete', before, None)
            vessel = get_vessel(db, vessel_id)
        return jsonify(deleted=True, vessel=vessel, projection_applied=vessel.get('calculation_mode') == 'calculated')
