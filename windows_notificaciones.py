"""Avisos de Windows para expedientes con plazos confirmados.

No envía correo ni altera vencimientos. Una notificación se marca como mostrada
solo tras aceptar el transporte; el sistema operativo puede ocultarla por sus
preferencias de notificación o por Asistente de concentración.
"""
import sys
from datetime import date


def upcoming_notifications(today=None):
    from app import current_deadlines
    today = today or date.today()
    notices = []
    for v in current_deadlines():
        # Las referencias históricas aceptadas solo para consulta NO son plazos
        # confirmados y no pueden generar alarmas automáticas.
        if v.get('date_quality') != 'confirmado':
            continue
        if v.get('archived_closure_date') or v.get('closure_due_to_90_days') or v.get('stage') == 'cierre':
            continue
        if v.get('temporarily_away'):
            deadline = v.get('return_deadline')
            category = 'retorno_temporal'
            prefix = 'Retorno de salida temporal'
            thresholds = (30, 15, 7, 1, 0)
        else:
            deadline = v.get('operational_date') or v.get('expiry_date')
            category = 'permiso'
            prefix = 'Vencimiento de permiso'
            thresholds = (30, 15, 1, 0)
        if not deadline:
            continue
        try:
            deadline_date = date.fromisoformat(deadline)
            remaining = (deadline_date - today).days
        except (ValueError, TypeError):
            continue
        if remaining not in thresholds:
            continue
        subject = (v.get('name') or v.get('declaration') or 'Embarcación').strip()
        title = f'SERVAMAR · {prefix}'
        body = (f'{subject} · {v.get("declaration") or ""} · '
                + ('Plazo vence hoy' if remaining == 0 else f'{remaining} día(s) restantes')
                + ' · ' + deadline_date.strftime('%d/%m/%Y'))
        notices.append({'vessel_id': v['id'], 'category': category,
                        'deadline': deadline, 'days_before': remaining,
                        'title': title, 'body': body})
    return notices


def preview_windows_notifications(today=None):
    return {'date': (today or date.today()).isoformat(),
            'notifications': upcoming_notifications(today), 'email_sent': False,
            'note': 'Solo plazos confirmados. No se envían notificaciones en la vista previa.'}


def run_windows_notifications(today=None, transport=None):
    if transport is None:
        if sys.platform != 'win32':
            raise RuntimeError('Las notificaciones locales requieren Windows 10/11.')
        try:
            from winotify import Notification
        except ImportError as ex:
            raise RuntimeError('Instala dependencias: python -m pip install -r requirements.txt') from ex

        def transport(n):
            toast = Notification(app_id='SERVAMAR', title=n['title'],
                                 msg=n['body'], duration='long')
            toast.show()

    from app import conn
    notices = upcoming_notifications(today)
    delivered = 0
    skipped = 0
    failed = []
    for n in notices:
        key = (n['vessel_id'], n['category'], n['deadline'], n['days_before'])
        with conn() as c:
            exists = c.execute('SELECT 1 FROM windows_notice_log WHERE vessel_id=? AND category=? AND deadline=? AND days_before=?', key).fetchone()
        if exists:
            skipped += 1
            continue
        try:
            transport(n)
            with conn() as c:
                c.execute('INSERT OR IGNORE INTO windows_notice_log(vessel_id,category,deadline,days_before) VALUES(?,?,?,?)', key)
            delivered += 1
        except Exception as e:
            failed.append({'vessel_id': n['vessel_id'], 'error': type(e).__name__})
    return {'evaluated': len(notices), 'delivered_to_windows': delivered,
            'already_notified': skipped, 'errors': failed, 'email_sent': False,
            'note': 'Windows puede ocultar avisos por sus preferencias de notificaciones.'}
