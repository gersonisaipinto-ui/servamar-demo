"""Preview only: no transport, queue, scheduler or delivery side effects."""
from datetime import date, timedelta
from flask import jsonify
from postgres_test_reports import today_guatemala


def preview(vessel, first_name='cliente de prueba'):
    expiry = date.fromisoformat(vessel['expiry_date']) if vessel['expiry_date'] else None
    days = (expiry-today_guatemala()).days if expiry else None
    formatted = expiry.strftime('%d/%m/%Y') if expiry else 'sin fecha'
    name = vessel['name']
    manual = vessel.get('calculation_mode') != 'calculated'
    en = 'manually recorded' if manual else 'calculated'
    es = 'registrado manualmente' if manual else 'calculado'
    return dict(delivery_enabled=False,manual_dates=manual,days_remaining=days,
                subject=f'[PRUEBA SIN ENVÍO] SERVAMAR · {name} · {formatted}',
                body=f'Hello, {first_name}:\n\nThis is a fictional preview. The {en} expiry date for your vessel {name} is {formatted} ({days} days remaining). Please reply so we can review the permit.\n\nKind regards,\nRaúl Morales – SERVAMAR\n\n'
                     f'Hola, {first_name}:\n\nEsta es una vista previa ficticia. El vencimiento {es} de tu embarcación {name} es el {formatted} ({days} días restantes). Por favor contesta para que revisemos el permiso.\n\nAtentamente,\nRaúl Morales – SERVAMAR',
                reminders=[dict(days_before=d,date=(expiry-timedelta(days=d)).isoformat()) for d in (30,15,1)] if expiry else [],
                warning='Sin envíos. Recordatorios confirmados: 30, 15 y 1 días antes del vencimiento.')


def register(app, protected, connection, get_vessel, ApiError):
    @app.get('/api/test/vessels/<int:vessel_id>/notifications/preview')
    @protected
    def notification_preview(vessel_id):
        with connection() as db:
            vessel=get_vessel(db,vessel_id)
            contact=db.execute('SELECT full_name FROM servamar_test.v91_vessel_contacts WHERE vessel_id=%s '
                               'ORDER BY is_primary DESC,id LIMIT 1',(vessel_id,)).fetchone()
        if vessel.get('needs_review'):raise ApiError('Revisa el historial antes de preparar un recordatorio',409)
        if not vessel['expiry_date']:raise ApiError('Registra un vencimiento manual para generar la vista previa',409)
        if vessel['stage'] not in ('ingreso','ampliacion','deposito'):
            raise ApiError('La etapa no corresponde a un permiso vigente para este recordatorio',409)
        return jsonify(preview(vessel,contact[0].split()[0] if contact and contact[0].split() else 'cliente de prueba'))

    @app.post('/api/test/vessels/<int:vessel_id>/notifications/send')
    @protected
    def disabled_delivery(vessel_id):
        raise ApiError('Envíos deshabilitados: se requiere autorización explícita y configurar un transporte de pruebas',403)
