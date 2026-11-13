"""Avisos genéricos y opcionales a Android vía ntfy.sh.

Nunca envía nombres, ST, fechas, correos, documentos ni contraseñas.
El tema de ntfy es público, por lo que se usa uno aleatorio y no adivinable.
No se instala ni activa ningún envío hasta ejecutar el asistente explícito.
"""
import json
import re
import ssl
import urllib.request
from datetime import date, datetime
from pathlib import Path

BASE_URL = 'https://ntfy.sh/'
CONFIG_NAME = 'android_push_config.json'


def config_path():
    from app import DATA_DIR
    return DATA_DIR / CONFIG_NAME


def load_config():
    path = config_path()
    if not path.exists():
        return None
    conf = json.loads(path.read_text(encoding='utf-8-sig'))
    topic = conf.get('topic', '')
    if not conf.get('enabled') or not re.fullmatch(r'servamar-[0-9a-f]{48,64}', topic):
        return None
    return conf


def due_notices(today=None):
    from windows_notificaciones import upcoming_notifications
    return upcoming_notifications(today)


def preview_android_notifications(today=None):
    today = today or date.today()
    notices = due_notices(today)
    return {
        'date': today.isoformat(), 'count': len(notices),
        'enabled': bool(load_config()), 'sent': False,
        'note': 'Solo resumen sin nombres, fechas ni documentos; no se ha enviado nada.'
    }


def publish_generic(topic, message, sender=None):
    if not re.fullmatch(r'servamar-[0-9a-f]{48,64}', topic):
        raise ValueError('Identificador de canal inválido')
    if sender is not None:
        return sender(topic, message)
    payload = message.encode('utf-8')
    req = urllib.request.Request(
        BASE_URL + topic, data=payload, method='POST',
        headers={'Title':'SERVAMAR - Avisos', 'Tags':'bell',
                 'Cache':'no', 'Content-Type':'text/plain; charset=utf-8'})
    with urllib.request.urlopen(req, timeout=12, context=ssl.create_default_context()) as resp:
        if not (200 <= resp.status < 300):
            raise RuntimeError('Proveedor de notificaciones no disponible')
    return True


def send_android_test(sender=None):
    conf = load_config()
    if not conf:
        return {'sent':False,'reason':'No activado. Ejecuta ACTIVAR_ALARMAS_ANDROID.bat'}
    publish_generic(conf['topic'], 'Prueba de conexión. SERVAMAR puede enviar avisos a este teléfono.', sender)
    return {'sent': True, 'kind':'test', 'no_private_data':True}


def run_android_notifications(today=None, sender=None):
    from app import conn
    today = today or date.today()
    conf = load_config()
    if not conf:
        return {'sent':False,'reason':'Canal Android no configurado'}
    notices = due_notices(today)
    if not notices:
        return {'sent':False,'count':0,'reason':'No hay recordatorios confirmados para hoy'}
    stamp = today.isoformat()
    with conn() as c:
        c.execute('CREATE TABLE IF NOT EXISTS android_push_log (day TEXT PRIMARY KEY, delivered_at TEXT NOT NULL, number_of_alerts INTEGER NOT NULL)')
        if c.execute('SELECT 1 FROM android_push_log WHERE day=?',(stamp,)).fetchone():
            return {'sent':False,'count':len(notices),'reason':'Aviso de hoy ya enviado'}
    count = len(notices)
    message = (f'Tienes {count} aviso(s) de vencimientos o salidas temporales. '
               'Abre SERVAMAR dentro de la Wi-Fi de la oficina para consultar los detalles.')
    publish_generic(conf['topic'], message, sender)
    with conn() as c:
        c.execute('INSERT OR IGNORE INTO android_push_log(day,delivered_at,number_of_alerts) VALUES(?,?,?)',
                  (stamp, datetime.now().isoformat(timespec='seconds'), count))
    return {'sent':True,'count':count,'no_private_data':True}
