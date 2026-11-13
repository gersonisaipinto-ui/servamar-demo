"""Correos periódicos SOLO a clientes expresamente autorizados.

Opciones separadas: vista previa no envía, prueba solo a administración,
y tarea diaria que requiere activación consciente. No modifica permisos.
"""
import json
import os
from datetime import date, datetime


def _backend():
    import app
    return app


def _eligible_rows(a, c, today):
    rows = c.execute("""SELECT v.*, s.days_before FROM vessels v
      JOIN alert_settings s ON s.vessel_id=v.id AND s.enabled=1
      WHERE v.validated=1 AND v.stage IN ('ingreso','ampliacion','deposito')
        AND v.expiry_date IS NOT NULL AND v.expiry_date!=''
        AND v.client_opt_in=1 AND v.client_send_approved=1
        AND v.email IS NOT NULL AND v.email!=''
        AND s.days_before IN (30,15,1)""").fetchall()
    for v in rows:
        expiry=a.requiredate(v['expiry_date'])
        if not expiry or a.due(expiry, v['days_before']) != today:
            continue
        if not a.valid_mail_address(v['email']):
            continue
        if a.historical_documented_closure(c,v['id']):
            continue
        temporary=a.temporary_exit_summary(c,v['id'],today)
        if temporary['currently_away'] or temporary['must_close']:
            continue
        # Only the currently recorded and validated permit; historical references
        # do not themselves authorize automatic correspondence.
        yield v,expiry


def preview(today=None):
    """Read only; never includes clients' e-mail addresses or transmits messages."""
    a=_backend(); today=today or date.today()
    items=[]
    with a.conn() as c:
        for v,exp in _eligible_rows(a,c,today):
            prior=c.execute("""SELECT status FROM alert_log WHERE vessel_id=?
              AND expiry_date=? AND days_before=? AND destination='client-auto'""",
              (v['id'],exp.isoformat(),v['days_before'])).fetchone()
            items.append({'vessel':v['name'],'declaration':v['declaration'],
                          'deadline':exp.isoformat(),'days_before':v['days_before'],
                          'delivery_status':prior['status'] if prior else 'pending'})
    return {'date':today.isoformat(),'candidates':len(items),
            'sending_enabled':_enabled(a),'items':items,
            'note':'Simulación; ningún mensaje enviado.'}


def _enabled(a):
    return (os.getenv('ENABLE_CLIENT_EMAIL')=='YES'
            and os.getenv('CONFIRM_EMAIL_SEND')=='YES'
            and a.mail_eligibility()['smtp_ready'])


def test_admin():
    """Sends one fictional bilingual template ONLY to configured ADMIN_EMAIL."""
    a=_backend()
    recipient=os.getenv('ADMIN_EMAIL')
    if not a.valid_mail_address(recipient):raise ValueError('Configura ADMIN_EMAIL válido')
    if not a.mail_eligibility()['smtp_ready']:raise ValueError('SMTP no configurado')
    from datetime import timedelta
    subject,body=a.render_mail_text('DEMO VESSEL / EMBARCACIÓN DEMO','ST-DEMO-000',date.today()+timedelta(days=15),'ingreso')
    a.send_email(recipient,'[PRUEBA INTERNA] '+subject,body,a.styled_mail_html(body))
    return {'ok':True,'note':'Prueba enviada únicamente al administrador, nunca a clientes'}


def _log_run(a, result):
    # Avoid logging email addresses, passwords, SMTP exceptions or client details.
    path=a.DATA_DIR/'logs';path.mkdir(parents=True,exist_ok=True)
    with (path/'correos_automaticos.jsonl').open('a',encoding='utf-8') as f:
        f.write(json.dumps({'at':datetime.now().isoformat(timespec='seconds'),**result},ensure_ascii=False)+'\n')


def send_clients_daily(today=None, deliver=None):
    """Fail closed unless explicitly activated.

    Mark each reminder 'reserved' before SMTP to prevent duplicate sends if the
    process crashes between SMTP delivery and recording success. Non-successful
    reservations require manual investigation, never blind automatic retries.
    """
    a=_backend()
    if not _enabled(a):
        raise RuntimeError('Correos automáticos desactivados. Revisa SMTP, ENABLE_CLIENT_EMAIL y CONFIRM_EMAIL_SEND.')
    today=today or date.today(); deliver=deliver or a.send_email
    result={'attempted':0,'sent':0,'failed':0,'skipped_prior':0}
    with a.lock:
        with a.conn() as c:
            entries=list(_eligible_rows(a,c,today))
        for v,exp in entries:
            key=(v['id'],exp.isoformat(),v['days_before'],'client-auto')
            with a.conn() as c:
                # All statuses block retries, including uncertain SMTP outcomes.
                prior=c.execute('''SELECT status FROM alert_log WHERE vessel_id=?
                  AND expiry_date=? AND days_before=? AND destination=?''',key).fetchone()
                if prior:
                    result['skipped_prior']+=1;continue
                c.execute('''INSERT INTO alert_log(vessel_id,expiry_date,days_before,destination,status,detail)
                  VALUES(?,?,?,?,?,?)''',(*key,'reserved','Reserva anterior a SMTP; verificar si hay fallo.'))
            result['attempted']+=1
            try:
                # Live sending takes place only after all conditions were checked.
                subject,body=a.render_mail_text(v['name'],v['declaration'],exp,v['stage'],captain=v['captain'])
                deliver(v['email'],subject,body,a.styled_mail_html(body))
            except Exception:
                with a.conn() as c:
                    c.execute('''UPDATE alert_log SET status='failed',detail='Fallo SMTP; revisar sin reintento automático'
                      WHERE vessel_id=? AND expiry_date=? AND days_before=? AND destination=?''',key)
                result['failed']+=1
            else:
                with a.conn() as c:
                    c.execute('''UPDATE alert_log SET status='sent',detail='Envío automático realizado'
                      WHERE vessel_id=? AND expiry_date=? AND days_before=? AND destination=?''',key)
                result['sent']+=1
    _log_run(a,result)
    return result
