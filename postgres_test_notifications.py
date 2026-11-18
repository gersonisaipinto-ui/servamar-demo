"""Expiry-based reminder plans only. No delivery transport or background worker."""
from datetime import date, timedelta
from flask import jsonify
from postgres_test_reports import today_guatemala


DAYS=(30,15,1)
CHANNELS=('email','push','windows')


def reminder_dates(vessel, today=None):
    today=today or today_guatemala()
    if vessel.get('needs_review') or vessel.get('stage') not in ('ingreso','ampliacion','deposito') or not vessel.get('expiry_date'):
        return []
    expiry=date.fromisoformat(vessel['expiry_date'])
    if expiry<today:return []
    return [dict(days_before=d,date=(expiry-timedelta(days=d)).isoformat(),
                 status='planned' if expiry-timedelta(days=d)>=today else 'elapsed') for d in DAYS]


def reconcile_schedule(db, vessel):
    """Caller holds the vessel lock; plans and expiry change atomically. Never sends."""
    today=today_guatemala();dates=reminder_dates(vessel,today)
    expiry=vessel.get('expiry_date') if dates else None
    db.execute('UPDATE servamar_test.vessels SET automatic_notices_suspended=FALSE, '
               'automatic_notices_reason=NULL WHERE id=%s AND (automatic_notices_suspended OR automatic_notices_reason IS NOT NULL)',(vessel['id'],))
    db.execute('UPDATE servamar_test.alert_settings SET enabled=FALSE WHERE vessel_id=%s AND enabled=TRUE',(vessel['id'],))
    cancelled=db.execute("UPDATE servamar_test.v96_notification_schedule SET status='cancelled' "
                         "WHERE vessel_id=%s AND status='planned' AND (expiry_date IS DISTINCT FROM %s::date OR due_date<%s)",
                         (vessel['id'],expiry,today)).rowcount
    # Preserve already sent and manual events; retire obsolete automatic retries.
    retired=db.execute("UPDATE servamar_test.v91_notification_events SET status='cancelled',error_code='expiry_recalculated' "
                       "WHERE vessel_id=%s AND kind IN ('expiry_30','expiry_15','expiry_1') AND status IN ('pending','failed') "
                       "AND ((due_date + CASE kind WHEN 'expiry_30' THEN 30 WHEN 'expiry_15' THEN 15 ELSE 1 END) "
                       "IS DISTINCT FROM %s::date OR due_date<%s)",(vessel['id'],expiry,today)).rowcount
    for reminder in dates:
        if reminder['status']!='planned':continue
        for channel in CHANNELS:
            db.execute("INSERT INTO servamar_test.v96_notification_schedule(vessel_id,expiry_date,days_before,due_date,channel,status) "
                       "SELECT %s,%s,%s,%s,%s,'planned' WHERE NOT EXISTS (SELECT 1 FROM servamar_test.v91_notification_events "
                       "WHERE vessel_id=%s AND channel=%s AND kind=%s AND due_date=%s AND status='sent') "
                       "ON CONFLICT(vessel_id,expiry_date,days_before,channel) DO UPDATE SET status='planned' "
                       "WHERE servamar_test.v96_notification_schedule.status='cancelled'",
                       (vessel['id'],expiry,reminder['days_before'],reminder['date'],channel,
                        vessel['id'],channel,'expiry_'+str(reminder['days_before']),reminder['date']))
    # A historical sent event wins over a restored plan for the same deadline.
    db.execute("UPDATE servamar_test.v96_notification_schedule p SET status='cancelled' WHERE p.vessel_id=%s AND p.status='planned' "
               "AND EXISTS (SELECT 1 FROM servamar_test.v91_notification_events e WHERE e.vessel_id=p.vessel_id "
               "AND e.channel=p.channel AND e.kind='expiry_'||p.days_before::text AND e.due_date=p.due_date AND e.status='sent')",(vessel['id'],))
    return dict(expiry_date=expiry,cancelled_plans=cancelled,cancelled_events=retired,delivery_enabled=False)


def automatic_status(vessel):
    return dict(suspended=False,reason=None,email_enabled=False,notifications_enabled=False,
                expiry_date=vessel.get('expiry_date'),
                message='Avisos recalculados según el vencimiento actual: 30, 15 y 1 días antes. Los envíos reales siguen deshabilitados en pruebas.')


def preview(vessel, first_name='cliente de prueba'):
    expiry = date.fromisoformat(vessel['expiry_date']) if vessel['expiry_date'] else None
    days = (expiry-today_guatemala()).days if expiry else None
    formatted = expiry.strftime('%d/%m/%Y') if expiry else 'sin fecha'
    name = vessel['name']
    manual = vessel.get('calculation_mode') != 'calculated'
    en = 'manually recorded' if manual else 'calculated'
    es = 'registrado manualmente' if manual else 'calculado'
    automatic=automatic_status(vessel)
    return dict(delivery_enabled=False,manual_dates=manual,days_remaining=days,automatic=automatic,
                subject=f'[PRUEBA SIN ENVÍO] SERVAMAR · {name} · {formatted}',
                body=f'Hello, {first_name}:\n\nThis is a fictional preview. The {en} expiry date for your vessel {name} is {formatted} ({days} days remaining). Please reply so we can review the permit.\n\nKind regards,\nRaúl Morales – SERVAMAR\n\n'
                     f'Hola, {first_name}:\n\nEsta es una vista previa ficticia. El vencimiento {es} de tu embarcación {name} es el {formatted} ({days} días restantes). Por favor contesta para que revisemos el permiso.\n\nAtentamente,\nRaúl Morales – SERVAMAR',
                reminders=reminder_dates(vessel),warning=automatic['message'])


def register(app, protected, connection, get_vessel, ApiError):
    @app.get('/api/test/vessels/<int:vessel_id>/notifications/plan')
    @protected
    def notification_plan(vessel_id):
        today=today_guatemala()
        with connection() as db:
            vessel=get_vessel(db,vessel_id)
            eligible=bool(reminder_dates(vessel,today))
            rows=db.execute("SELECT p.expiry_date,p.days_before,p.due_date,p.channel,p.status, "
                            "EXISTS (SELECT 1 FROM servamar_test.v91_notification_events e WHERE e.vessel_id=p.vessel_id "
                            "AND e.channel=p.channel AND e.kind='expiry_'||p.days_before::text AND e.due_date=p.due_date AND e.status='sent') "
                            "FROM servamar_test.v96_notification_schedule p WHERE p.vessel_id=%s "
                            "ORDER BY (p.expiry_date=%s::date) DESC,p.expiry_date DESC,p.due_date,p.channel LIMIT 301",(vessel_id,vessel.get('expiry_date'))).fetchall()
        plans=[]
        for expiry,days,due,channel,status,sent in rows[:300]:
            if sent:status='sent'
            elif status=='planned' and (not eligible or expiry.isoformat()!=vessel['expiry_date']):status='cancelled'
            elif status=='planned' and due<today:status='elapsed'
            plans.append(dict(expiry_date=expiry.isoformat(),days_before=days,date=due.isoformat(),channel=channel,status=status))
        return jsonify(expiry_date=vessel.get('expiry_date'),plans=plans,capped=len(rows)>300,delivery_enabled=False)

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
