"""Control de embarcaciones - aplicación local. No envía notificaciones sin configuración SMTP."""
import os, sqlite3, json, threading, smtplib, ssl, calendar, csv, io, sys, re
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from flask import Flask, request, jsonify, render_template, send_file, abort, send_from_directory
from functools import wraps
import hmac, secrets, uuid, hashlib, zipfile, shutil
from xml.sax.saxutils import escape as xml_escape
from html import escape as html_escape
ROOT=Path(__file__).resolve().parent
# Separar datos de la versión instalable: futuras versiones usan esta misma carpeta.
DEMO_MODE=os.getenv('SERVAMAR_DEMO_MODE','').upper()=='YES'
DATA_DIR=(Path('/tmp/servamar_demo_v60') if DEMO_MODE else Path(os.environ.get('SERVAMAR_DATA_DIR') or (Path(os.environ.get('LOCALAPPDATA') or (Path.home()/'AppData'/'Local'))/'SERVAMAR_LIMPIO')))
# CLOUD_MODE requires persistent storage and credentials before handling data.
CLOUD_MODE=os.getenv('SERVAMAR_CLOUD_MODE','').upper()=='YES'
if CLOUD_MODE:
 if not os.getenv('APP_PASSWORD') or len(os.getenv('APP_PASSWORD','')) < 16:
  raise RuntimeError('SERVAMAR nube: configura APP_PASSWORD de al menos 16 caracteres antes de arrancar.')
 if not os.getenv('APP_USERNAME'):
  raise RuntimeError('SERVAMAR nube: configura APP_USERNAME antes de arrancar.')
 if not DEMO_MODE and not os.getenv('SERVAMAR_DATA_DIR'):
  raise RuntimeError('SERVAMAR nube: SERVAMAR_DATA_DIR debe apuntar al disco persistente.')
 if not DEMO_MODE:
  data_mount=Path('/var/data')
  if not data_mount.is_dir() or not os.path.ismount(str(data_mount)):
   raise RuntimeError('SERVAMAR nube: disco persistente /var/data no montado; no se inicia.')
  if not Path(os.getenv('SERVAMAR_DATA_DIR')).resolve().is_relative_to(data_mount.resolve()):
   raise RuntimeError('SERVAMAR nube: SERVAMAR_DATA_DIR debe estar dentro de /var/data.')
DATA_DIR.mkdir(parents=True,exist_ok=True)
# Primer arranque: base de ejemplo del paquete. La migración de datos reales se
# realiza por la utilidad MIGRAR_DATOS_ANTERIORES, sin sobrescribir la base existente.
if not (DATA_DIR/'embarcaciones.sqlite3').exists() and (ROOT/'embarcaciones.sqlite3').exists():
 shutil.copy2(ROOT/'embarcaciones.sqlite3',DATA_DIR/'embarcaciones.sqlite3')

def load_local_mail_settings(path=None):
 """Load optional private SMTP settings without overriding process environment.
 No eval, interpolation or shell expansion. Local only.
 """
 path=Path(path) if path else DATA_DIR/'correo_local.env'
 if not path.is_file():return False
 allowed={'SMTP_HOST','SMTP_PORT','SMTP_USER','SMTP_PASSWORD','SMTP_FROM','ADMIN_EMAIL',
          'ENABLE_CLIENT_EMAIL','CONFIRM_EMAIL_SEND','ENABLE_ADMIN_AUTOMATION'}
 for raw in path.read_text(encoding='utf-8-sig').splitlines():
  line=raw.strip()
  if not line or line.startswith('#') or '=' not in line:continue
  key,value=line.split('=',1);key=key.strip();value=value.strip()
  if key in allowed and value and key not in os.environ:os.environ[key]=value
 return True
load_local_mail_settings()
from lan_security import lan_is_enabled, check_lan_credentials, lan_config_path
LAN_MODE=lan_is_enabled(DATA_DIR) and not CLOUD_MODE
DB=Path(os.environ.get('BOATS_DB',str(DATA_DIR/'embarcaciones.sqlite3')))
app=Flask(__name__)
if DEMO_MODE:
 from push_demo import init_push
 init_push(app,DATA_DIR)
 if CLOUD_MODE:
  from demo_vessels import init_demo_vessels
  init_demo_vessels(app)

@app.get('/push-sw.js')
def serve_push_worker():
 response=send_from_directory(ROOT,'push-sw.js',mimetype='text/javascript')
 response.headers['Service-Worker-Allowed']='/'
 return response

VERSION='62'
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024

@app.before_request
def basic_protection():
 # Render uses a TLS-terminating proxy. HTTPS is mandatory for cloud-facing data.
 if CLOUD_MODE and request.path != '/healthz' and request.headers.get('X-Forwarded-Proto','').split(',')[0].strip() != 'https':
  return jsonify(error='HTTPS obligatorio'),403
 if request.path == '/healthz' and not LAN_MODE:
  return None
 if DEMO_MODE and request.method not in ('GET','HEAD','OPTIONS') and request.path not in ('/api/push/subscribe','/api/push/unsubscribe','/api/push/test','/api/push/daily-check','/api/push/demo-reminder-test') and not (request.path == '/api/demo/vessels' or request.path.startswith('/api/demo/vessels/')):
  return jsonify(error='DEMO GRATUITA: solo lectura. No se permiten modificaciones, importaciones ni envíos.'),403
 if LAN_MODE:
  from ipaddress import ip_address
  try:
   remote=ip_address(request.remote_addr)
  except ValueError:
   return jsonify(error='IP no autorizada'),403
  if not (remote.is_private or remote.is_loopback):
   return jsonify(error='Acceso solo para red local'),403
  auth=request.authorization
  if not auth or not check_lan_credentials(DATA_DIR, auth.username or '', auth.password or ''):
   return ('Usuario y contrasena requeridos',401,{'WWW-Authenticate':'Basic realm="SERVAMAR red local"'})
  if request.method in ('POST','PUT','PATCH','DELETE'):
   from urllib.parse import urlsplit
   if request.headers.get('Sec-Fetch-Site','').lower() == 'cross-site':
    return jsonify(error='Origen externo bloqueado'),403
   if request.headers.get('Origin'):
    origin=urlsplit(request.headers['Origin'])
    if origin.netloc != request.host or origin.scheme!='http':
     return jsonify(error='Origen no autorizado'),403
  return None
 if not os.getenv('APP_PASSWORD'):
  if request.remote_addr not in ('127.0.0.1','::1'):
   return jsonify(error='Para acceso remoto configurar APP_PASSWORD y HTTPS'),403
  return None
 auth=request.authorization
 username_ok=not CLOUD_MODE or hmac.compare_digest((auth.username if auth else '') or '',os.environ.get('APP_USERNAME',''))
 password_ok=bool(auth) and hmac.compare_digest((auth.password if auth else '') or '',os.environ['APP_PASSWORD'])
 if not (username_ok and password_ok):
  return ('Autenticación requerida',401,{'WWW-Authenticate':'Basic realm="SERVAMAR privado"'})
 if request.method in ('POST','PUT','PATCH','DELETE'):
  if request.headers.get('Sec-Fetch-Site','').lower() == 'cross-site':
   return jsonify(error='Origen externo bloqueado'),403
  if request.headers.get('Origin'):
   from urllib.parse import urlsplit
   origin=urlsplit(request.headers['Origin'])
   if origin.netloc!=request.host or (CLOUD_MODE and origin.scheme!='https'):
    return jsonify(error='Origen no autorizado'),403

@app.after_request
def privacy_headers(response):
 response.headers['Cache-Control']='no-store, private'
 response.headers['X-Content-Type-Options']='nosniff'
 response.headers['X-Frame-Options']='DENY'
 response.headers['Referrer-Policy']='no-referrer'
 response.headers['Content-Security-Policy']="frame-ancestors 'none'"
 if CLOUD_MODE:
  response.headers['Strict-Transport-Security']='max-age=31536000; includeSubDomains'
 return response

@app.get('/healthz')
def healthz():
 return jsonify(status='ok')

lock=threading.RLock()
def conn():
 c=sqlite3.connect(DB,timeout=25);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');return c
def init():
 with conn() as c:
  c.executescript('''CREATE TABLE IF NOT EXISTS vessels(id INTEGER PRIMARY KEY, declaration TEXT NOT NULL, name TEXT, captain TEXT, email TEXT DEFAULT '', client_opt_in INTEGER DEFAULT 0, stage TEXT DEFAULT 'revision', start_date TEXT, expiry_date TEXT, validated INTEGER DEFAULT 0, notes TEXT DEFAULT '', UNIQUE(declaration, name));
  CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY, vessel_id INTEGER NOT NULL REFERENCES vessels(id), source_id TEXT, kind TEXT NOT NULL, event_date TEXT, expiry_date TEXT, description TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(source_id,kind));
  CREATE TABLE IF NOT EXISTS alert_settings(vessel_id INTEGER REFERENCES vessels(id), days_before INTEGER, enabled INTEGER DEFAULT 1, PRIMARY KEY(vessel_id,days_before));
  CREATE TABLE IF NOT EXISTS alert_log(id INTEGER PRIMARY KEY, vessel_id INTEGER, expiry_date TEXT, days_before INTEGER, destination TEXT, status TEXT, detail TEXT, sent_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(vessel_id,expiry_date,days_before,destination));''')
  # Migración segura de versión anterior (no altera registros).
  columns=[r[1] for r in c.execute('PRAGMA table_info(vessels)').fetchall()]
  if 'client_send_approved' not in columns:c.execute('ALTER TABLE vessels ADD COLUMN client_send_approved INTEGER DEFAULT 0')
  if 'registration_number' not in columns:c.execute("ALTER TABLE vessels ADD COLUMN registration_number TEXT NOT NULL DEFAULT ''")
  c.execute('CREATE INDEX IF NOT EXISTS idx_vessels_registration ON vessels(registration_number COLLATE NOCASE)')
  for col in ('closure_date','reentry_eligible_date','closure_reason'):
   if col not in columns:c.execute('ALTER TABLE vessels ADD COLUMN '+col+' TEXT')
  c.execute('''CREATE TABLE IF NOT EXISTS windows_notice_log(vessel_id INTEGER NOT NULL, category TEXT NOT NULL, deadline TEXT NOT NULL, days_before INTEGER NOT NULL, delivered_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(vessel_id,category,deadline,days_before))''')
  c.execute('''CREATE TABLE IF NOT EXISTS permit_documents(id INTEGER PRIMARY KEY, vessel_id INTEGER NOT NULL REFERENCES vessels(id), file_name TEXT NOT NULL, storage_name TEXT NOT NULL UNIQUE, mime TEXT NOT NULL, sha256 TEXT NOT NULL, uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(vessel_id,sha256))''')
  c.execute('''CREATE TABLE IF NOT EXISTS edit_audit(id INTEGER PRIMARY KEY, vessel_id INTEGER NOT NULL REFERENCES vessels(id), changed_at TEXT DEFAULT CURRENT_TIMESTAMP, changes TEXT NOT NULL)''')
  c.execute('''CREATE TABLE IF NOT EXISTS movement_before_state(history_id INTEGER PRIMARY KEY REFERENCES history(id), vessel_id INTEGER NOT NULL, state_json TEXT NOT NULL)''')
  c.execute('''CREATE TABLE IF NOT EXISTS movement_edit_audit(id INTEGER PRIMARY KEY, vessel_id INTEGER NOT NULL, history_id INTEGER NOT NULL, changed_at TEXT DEFAULT CURRENT_TIMESTAMP, before_json TEXT NOT NULL, changes_json TEXT NOT NULL, backup_name TEXT NOT NULL)''')
  c.execute('''CREATE TABLE IF NOT EXISTS movement_deletion_audit(id INTEGER PRIMARY KEY, vessel_id INTEGER NOT NULL, deleted_history_id INTEGER NOT NULL, deleted_at TEXT DEFAULT CURRENT_TIMESTAMP, deleted_row_json TEXT NOT NULL, previous_state_json TEXT NOT NULL, backup_name TEXT NOT NULL)''')
  if c.execute('SELECT COUNT(*) FROM vessels').fetchone()[0]:return
  # V42: instalación deliberadamente vacía; altas manuales o importación explícita.
  return

def requiredate(x):
 if not x:return None
 try:return date.fromisoformat(str(x))
 except:return None
def subtract_month(d):
 y=d.year;m=d.month-1
 if m==0:y-=1;m=12
 return date(y,m,min(d.day,calendar.monthrange(y,m)[1]))
def add_calendar_months(d, months):
 """Sumar meses calendario; ajustar día a último día del mes destino."""
 absolute=d.year*12+(d.month-1)+months
 year,month_index=divmod(absolute,12)
 return date(year,month_index+1,min(d.day,calendar.monthrange(year,month_index+1)[1]))

def initial_expiry_for_vessel(c,v):
 """Usar permiso inicial documentado en la ficha o el historial, sin autorizarlo implícitamente."""
 if v['validated'] and v['stage']=='ingreso':
  current=requiredate(v['expiry_date'])
  if current:return current, 'permiso inicial confirmado'
 rows=c.execute("SELECT event_date,expiry_date FROM history WHERE vessel_id=? AND kind='ingreso'",(v['id'],)).fetchall()
 candidates=[]
 for r in rows:
  start=requiredate(r['event_date']);end=requiredate(r['expiry_date'])
  if start and end and end>=start:
   candidates.append((start,end))
 if not candidates:return None, 'no existe vencimiento inicial legible'
 # Priorizar el ingreso documentado más reciente, para no aplicar ampliaciones a otro período.
 start,end=max(candidates,key=lambda x:(x[0],x[1]))
 return end,'vencimiento inicial del historial (verificar contra documento)'

def initial_entry_for_vessel(c,v):
 """Ingreso del periodo más reciente; nunca inferir un permiso aprobado."""
 rows=c.execute("SELECT event_date FROM history WHERE vessel_id=? AND kind='ingreso'",(v['id'],)).fetchall()
 dates=[requiredate(r['event_date']) for r in rows]
 dates=[d for d in dates if d]
 if v['validated'] and v['stage']=='ingreso' and requiredate(v['start_date']):
  dates.append(requiredate(v['start_date']))
 if not dates: return None
 return max(dates)

# V41: un "CIERRE DE PERMISO" en las observaciones importadas es un cierre,
# no una salida temporal abierta. Se interpreta solo si existe una fecha explícita.
# No se modifica el registro fuente ni se inventa una resolución.
def historical_documented_closure(c, vessel_id):
 rows=c.execute("SELECT kind,event_date,description FROM history WHERE vessel_id=?",(vessel_id,)).fetchall()
 closes=[];entries=[]
 for r in rows:
  kind=r['kind'];d=requiredate(r['event_date'])
  if kind=='ingreso' and d:entries.append(d)
  if kind in ('cierre','cierre_automatico') and d:closes.append(d)
  if kind=='salida_archivo':
   label=re.search(r'\bCIERRE\s+DE\s+PERMISO\b\s*[:\-]?\s*(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b',str(r['description'] or ''),re.I)
   if label:
    try:closes.append(date(int(label.group(3)),int(label.group(2)),int(label.group(1))))
    except ValueError:pass
 if not closes:return None
 latest=max(closes)
 # Un ingreso documentado posterior inicia otro permiso y prevalece sobre el cierre antiguo.
 if entries and max(entries)>latest:return None
 return latest

# V37: reconciliación de salidas temporales escritas como observaciones en los Excel.
# La fecha en texto se convierte en fecha estructurada solo cuando la etiqueta
# y el formato son inequívocos. Se conserva íntegra la observación de origen.
HISTORICAL_TEMPORARY_KINDS=('salida_archivo','retorno_archivo')

def historical_temporary_date(kind,description):
 text=' '.join(str(description or '').upper().split())
 if kind=='salida_archivo':
  if not re.search(r'\bSALIDA\s+TEMPORAL\b',text):return None
 elif kind=='retorno_archivo':
  if not re.search(r'\bRETORNO\s+DE\s+SALIDA\s+TEMP(?:ORAL|AORAL)\b',text):return None
 else:return None
 # Buscar fecha próxima a la etiqueta, evitando fechas de VENCE/VENCIMIENTO.
 pattern=(r'\bSALIDA\s+TEMPORAL\s*[:\-]?\s*' if kind=='salida_archivo'
          else r'\bRETORNO\s+DE\s+SALIDA\s+TEMP(?:ORAL|AORAL)\s*[:\-]?\s*')
 match=re.search(pattern+r'(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b',text)
 if not match:return None
 try:return date(int(match.group(3)),int(match.group(2)),int(match.group(1)))
 except ValueError:return None

def reconcile_historical_temporary_dates_once():
 """Poblar event_date de anotaciones inequívocas. Sin crear permisos ni cierres.
 Respaldo SQLite antes de modificar; la migración es repetible y conserva el texto.
 """
 with lock,conn() as c:
  c.execute('CREATE TABLE IF NOT EXISTS app_migrations (name TEXT PRIMARY KEY, applied_at TEXT DEFAULT CURRENT_TIMESTAMP, detail TEXT)')
  if c.execute("SELECT 1 FROM app_migrations WHERE name='v37_historical_temporary_dates'").fetchone():return
  rows=c.execute("SELECT id,kind,description FROM history WHERE kind IN ('salida_archivo','retorno_archivo') AND (event_date IS NULL OR event_date='')").fetchall()
  updates=[]
  for r in rows:
   extracted=historical_temporary_date(r['kind'],r['description'])
   if extracted:updates.append((extracted.isoformat(),r['id']))
  if updates:
   folder=DATA_DIR/'backups';folder.mkdir(parents=True,exist_ok=True)
   backup_path=folder/('antes_conciliacion_salidas_v37_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.sqlite3')
   with sqlite3.connect(backup_path) as backup:c.backup(backup)
   c.executemany('UPDATE history SET event_date=? WHERE id=?',updates)
  c.execute('INSERT INTO app_migrations(name,detail) VALUES (?,?)',('v37_historical_temporary_dates',f'{len(updates)} fechas de salidas/retornos estructuradas desde observaciones; sin modificar estados ni vencimientos'))

def temporary_exit_summary(c,vessel_id,today=None,rows=None):
 """Reconcilia movimientos manuales y fechas explícitas de observaciones Excel.
 No presume retorno cuando falta ni altera vencimientos históricos por inferencia.
 """
 today=today or date.today()
 if rows is None:
  rows=c.execute("""SELECT id,kind,event_date,source_id,description FROM history
      WHERE vessel_id=? AND kind IN ('salida','retorno','salida_archivo','retorno_archivo')
      ORDER BY event_date,id""",(vessel_id,)).fetchall()
 movements=[]
 for r in rows:
  kind=r['kind']; d=requiredate(r['event_date'])
  if not d and kind in HISTORICAL_TEMPORARY_KINDS:
   d=historical_temporary_date(kind,r['description'] if 'description' in r.keys() else '')
  if d:
   movements.append((d,int(r['id']),
                     'salida' if kind in ('salida','salida_archivo') else 'retorno',
                     kind in HISTORICAL_TEMPORARY_KINDS))
 movements.sort(key=lambda x:(x[0],x[1]))
 periods=[];open_date=None;open_historical=False;warnings=[]
 for d,_,kind,historical in movements:
  if kind=='salida':
   if open_date is not None:
    warnings.append('Hay otra salida sin retorno previo: revisar las observaciones.')
    continue
   open_date=d;open_historical=historical
  elif open_date is None:warnings.append('Retorno sin salida previa: revisar el expediente.')
  elif d<open_date:warnings.append('Retorno anterior a salida: revisar el expediente.')
  else:
   days=(d-open_date).days
   periods.append({'departure':open_date.isoformat(),'return':d.isoformat(),
                   'days_away':days,'historical':open_historical or historical,
                   'return_manual':not historical,
                   'status':'retornó' if days<90 else 'retorno tardío / revisar'})
   if days>=90:warnings.append('Retorno después del límite de 90 días: revisar cierre.')
   open_date=None;open_historical=False
 days_out=max(0,(today-open_date).days) if open_date else 0
 if open_date is not None:
  periods.append({'departure':open_date.isoformat(),'return':None,'days_away':days_out,
                  'historical':open_historical,
                  'status':'plazo de retorno agotado / verificar cierre' if days_out>=90 else 'fuera temporalmente'})
 if open_historical and days_out>=90:
  warnings.append('Salida importada con 90 días cumplidos y sin retorno documentado: revisar si hubo retorno o cierre. No se modifica automáticamente el acto administrativo.')
 return {'currently_away':open_date is not None,
         'historical_departure':bool(open_date is not None and open_historical),
         'current_departure':open_date.isoformat() if open_date else None,
         'current_days_away':days_out,
         'return_deadline':(open_date+timedelta(days=90)).isoformat() if open_date else None,
         'return_days_left':90-days_out if open_date else None,
         'must_close':open_date is not None and days_out>=90,
         'total_days_away':sum(x['days_away'] for x in periods),
         # Solo movimientos manuales confirmados ajustan automáticamente vencimientos.
         'days_added':sum(x['days_away'] for x in periods if x['return'] and x['days_away']<90 and x.get('return_manual',False)),
         'historical_days_for_review':sum(x['days_away'] for x in periods if x['return'] and x['days_away']<90 and not x.get('return_manual',False)),
         'periods':periods,'warnings':warnings,
         'note':'Los retornos manuales oportunos añaden los días fuera al vencimiento, aunque la salida original se haya importado del Excel. Los retornos históricos sin ajuste confirmado se muestran aparte.'}

def reconcile_temporary_closures(c,today=None):
 """Persistir cierres cuando el sistema se abre o ejecuta una tarea programada.
 Idempotente; nunca autoriza prórrogas ni envía mensajes.
 """
 today=today or date.today();closed=[]
 for v in c.execute("SELECT * FROM vessels WHERE validated=1 AND stage IN ('ingreso','ampliacion')").fetchall():
  ex=temporary_exit_summary(c,v['id'],today)
  if not ex['must_close'] or ex['historical_departure']:continue
  closure=requiredate(ex['return_deadline'])
  reentry=closure+timedelta(days=90)
  c.execute("""INSERT INTO history(vessel_id,kind,event_date,description)
               VALUES(?,?,?,?)""",(v['id'],'cierre_automatico',closure.isoformat(),
                  'Sin retorno dentro de los 90 días desde '+ex['current_departure']+'; cierre según regla configurada'))
  c.execute("""UPDATE vessels SET stage='cierre',expiry_date='',validated=1,
               closure_date=?,reentry_eligible_date=?,closure_reason='salida temporal sin retorno'
               WHERE id=?""",(closure.isoformat(),reentry.isoformat(),v['id']))
  closed.append(v['id'])
 return closed

# El cierre puede procesarse durante el uso local y mediante --reconcile-closures.
@app.before_request
def reconcile_before_request():
 if request.endpoint=='static':return None
 with lock,conn() as c:reconcile_temporary_closures(c)

def movement_context(c, vessel):
 """For recording a new movement, use the historical deadline displayed to the
 operator if this vessel has not yet been given a confirmed current state.
 This does not mark the historical authorization as verified, nor enable mail.
 """
 v=dict(vessel)
 if v['stage']!='revision':
  return v
 candidates=[]
 for h in c.execute("""SELECT kind, expiry_date FROM history
    WHERE vessel_id=? AND kind IN ('ingreso','ampliacion_archivo','deposito_archivo')""",(v['id'],)):
  exp=requiredate(h['expiry_date'])
  if exp:candidates.append((exp,h['kind']))
 if candidates:
  exp,kind=max(candidates,key=lambda x:(x[0],{'ingreso':0,'ampliacion_archivo':1,'deposito_archivo':2}[x[1]]))
  v['expiry_date']=exp.isoformat()
  v['stage']={'ingreso':'ingreso','ampliacion_archivo':'ampliacion','deposito_archivo':'deposito'}[kind]
 elif requiredate(v['expiry_date']):
  v['stage']='ingreso'
 return v

def calculate_movement(c,v,kind,start):
 archived_closure=historical_documented_closure(c,v['id'])
 if archived_closure:
  if kind!='ingreso':raise ValueError('Permiso cerrado el '+archived_closure.strftime('%d/%m/%Y')+'. No admite movimientos del permiso anterior.')
  if start is None or start<archived_closure+timedelta(days=90):
   raise ValueError('El nuevo ingreso solo procede 90 días después del cierre registrado.')
  # Permitir reingreso posterior sin tratar el vencimiento histórico como permiso vigente.
  v=dict(v);v['stage']='cierre';v['validated']=1;v['expiry_date']='';v['reentry_eligible_date']=(archived_closure+timedelta(days=90)).isoformat()
 v=movement_context(c,v)
 stage=v['stage'];verified=bool(v['validated']) and v['stage']!='revision'
 # La fecha de autorización de ampliación es opcional; el plazo depende del ingreso inicial.
 reference_date=start if start is not None else date.today()
 info=temporary_exit_summary(c,v['id'],reference_date)
 if kind=='ingreso':
  if verified and stage!='cierre' and requiredate(v['expiry_date']):
   raise ValueError('Hay un permiso vigente o pendiente de cierre; no se puede registrar otro ingreso.')
  eligible=requiredate(v['reentry_eligible_date']) if 'reentry_eligible_date' in v.keys() else None
  if eligible and start<eligible:
   raise ValueError('Reingreso bloqueado hasta '+eligible.strftime('%d/%m/%Y')+' (90 días después del cierre).')
  if info['currently_away'] and not (verified and stage=='cierre'):
   raise ValueError('Existe una salida temporal sin retorno; revisa el cierre primero.')
  return start+timedelta(days=90),'90 días desde el nuevo ingreso'
 if kind=='ampliacion':
  if verified and stage not in ('ingreso','revision'):
   raise ValueError('Solo puede ampliarse un permiso inicial no cerrado. Revisa el estado.')
  if info['currently_away'] and info['must_close']:
   raise ValueError('La salida temporal ya alcanzó los 90 días; permiso cerrado.')
  entry=initial_entry_for_vessel(c,v)
  if entry is None:raise ValueError('No existe fecha inicial de ingreso válida.')
  if start is not None and start<entry:raise ValueError('La fecha de autorización es anterior al ingreso.')
  # El año calendario aplica antes de acumular la suspensión por salidas oportunas.
  extension=info['days_added']
  return add_calendar_months(entry,12)+timedelta(days=extension),f'Un año calendario desde el ingreso + {extension} días de salidas temporales con retorno'
 if kind=='deposito':
  if info['currently_away']:raise ValueError('No se puede ingresar a depósito con una salida temporal abierta.')
  if verified and stage=='cierre':raise ValueError('El permiso está cerrado; registra un nuevo ingreso cuando corresponda.')
  return add_calendar_months(start,12),'12 meses desde la fecha efectiva de ingreso a depósito; sin salidas temporales'
 if kind=='salida':
  if info['currently_away']:raise ValueError('Ya existe una salida temporal abierta; registra el retorno.')
  if stage=='deposito':raise ValueError('En depósito aduanero no se permiten salidas temporales: registra el cierre definitivo.')
  if stage=='cierre':raise ValueError('El permiso está cerrado.')
  if stage not in ('revision','ingreso','ampliacion') or not requiredate(v['expiry_date']):
   raise ValueError('Falta una fecha de vencimiento válida para esta salida temporal. Para salida definitiva utiliza Cierre.')
  expiry=requiredate(v['expiry_date'])
  if start>expiry:raise ValueError('Permiso vencido: registra salida definitiva mediante Cierre; habrá 90 días antes de reingresar.')
  return start+timedelta(days=90),'Salida temporal: retorno antes de '+(start+timedelta(days=90)).strftime('%d/%m/%Y')+'; a los 90 días sin retorno se cierra el permiso'
 if kind=='retorno':
  if verified and stage=='cierre':raise ValueError('El permiso está cerrado; no admite retorno temporal.')
  if not info['currently_away']:raise ValueError('Registra primero una salida temporal.')
  # Las salidas importadas también admiten retorno manual: se usa su fecha de salida real.
  dep=requiredate(info['current_departure'])
  if start<dep:raise ValueError('El retorno no puede preceder a la salida.')
  days=(start-dep).days
  if days>=90:raise ValueError('Al cumplirse 90 días fuera el permiso se cierra. Registra un nuevo ingreso cuando corresponda.')
  if stage not in ('revision','ingreso','ampliacion') or not requiredate(v['expiry_date']):
   raise ValueError('No hay permiso con fecha vigente que pueda prorrogarse con el retorno.')
  new_expiry=requiredate(v['expiry_date'])+timedelta(days=days)
  return new_expiry,f'Retorno oportuno desde la salida {dep.strftime("%d/%m/%Y")}: {days} días fuera; {days} días agregados al vencimiento anterior'
 if kind=='cierre':
  if verified and stage=='cierre':raise ValueError('El expediente ya está cerrado.')
  # Permitir cierre manual aun cuando exista salida abierta; el cierre tiene prioridad.
  reentry=start+timedelta(days=90)
  return None,'Cierre y salida definitiva documentada; reingreso desde '+reentry.strftime('%d/%m/%Y')
 raise ValueError('Movimiento no reconocido')

@app.get('/api/vessels/<int:id>/movement-preview')
def movement_preview(id):
 kind=request.args.get('kind','')
 if kind not in ('ingreso','ampliacion','deposito','salida','retorno','cierre'):
  return jsonify(error='Movimiento inválido'),400
 raw_start=request.args.get('start_date','').strip()
 start=requiredate(raw_start)
 if (kind!='ampliacion' or raw_start) and not start:
  return jsonify(error='Indica una fecha válida dd/mm/yyyy para calcular el vencimiento'),400
 with conn() as c:
  v=c.execute('SELECT * FROM vessels WHERE id=?',(id,)).fetchone()
  if not v:return jsonify(error='Embarcación no encontrada'),404
  try:expiry,basis=calculate_movement(c,v,kind,start)
  except ValueError as e:return jsonify(error=str(e)),400
 return jsonify(expiry_date=expiry.isoformat() if expiry else '',basis=basis)

def declaration_rank(raw):
 """Orden ST-AAAA-NNN por año descendente y correlativo numérico descendente.
 No se confunde ST-2026-9 con ST-2026-100.
 """
 match=re.search(r'(?i)\bST\s*[-/ ]\s*(\d{4})\s*[-/ ]\s*(\d+)\b',str(raw or ''))
 if not match:return (-1,-1)
 return (int(match.group(1)),int(match.group(2)))

def search_deadline_sort_key(row, today=None):
 """Vigentes: vencimiento más próximo; después vencidos recientes; sin fecha al final.
 No ordena por ST; las fechas no confirmadas se muestran, pero siguen marcadas.
 """
 today=today or date.today()
 expiry=requiredate(row.get('current_expiry_date'))
 name=str(row.get('name') or '').casefold()
 if expiry is None:return (2,0,name,int(row.get('id') or 0))
 delta=(expiry-today).days
 return (0,delta,name,int(row.get('id') or 0)) if delta>=0 else (1,-delta,name,int(row.get('id') or 0))

def due(expiry,days):
 return subtract_month(expiry) if days==30 else expiry-timedelta(days=days)
def serialize(r):return dict(r)
@app.get('/')
def home():return render_template('index.html',demo_mode=DEMO_MODE)
# Nuevos ingresos y documentos: nunca convertir OCR en dato autorizado sin revisión humana.
DOC_DIR=DATA_DIR/'private_permits'
PENDING_DIR=DOC_DIR/'pending'
ALLOWED_DOCS={'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp','.pdf':'application/pdf'}

def safe_uploaded_document(file):
 filename=Path(file.filename or '').name
 suffix=Path(filename).suffix.lower()
 if suffix not in ALLOWED_DOCS:raise ValueError('Adjunta JPG, PNG, WEBP o PDF.')
 blob=file.read(12*1024*1024+1)
 if not blob or len(blob)>12*1024*1024:raise ValueError('Documento vacío o mayor a 12 MB.')
 if suffix=='.pdf':
  if not blob.startswith(b'%PDF-'):raise ValueError('El archivo no parece ser PDF.')
 else:
  try:
   from PIL import Image
   from io import BytesIO
   with Image.open(BytesIO(blob)) as img:img.verify()
  except Exception:raise ValueError('Imagen inválida o dañada.')
 return filename,suffix,blob

def _ocr_engine():
 """Find Tesseract on Windows even when its installer did not update PATH."""
 import shutil
 import pytesseract
 candidates=[os.environ.get('TESSERACT_CMD',''),shutil.which('tesseract'),
             r'C:\Program Files\Tesseract-OCR\tesseract.exe',
             r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe']
 for candidate in candidates:
  if candidate and Path(candidate).is_file():
   pytesseract.pytesseract.tesseract_cmd=str(candidate)
   return pytesseract
 raise RuntimeError('No se encontró Tesseract OCR. Instálalo en Windows y vuelve a probar; no basta con instalar pytesseract mediante pip.')

def _ocr_image(image,engine,notes):
 from PIL import ImageOps, ImageEnhance
 img=ImageOps.exif_transpose(image).convert('RGB')
 img.thumbnail((3600,3600))
 gray=ImageEnhance.Contrast(ImageOps.grayscale(img)).enhance(1.6)
 available=engine.get_languages(config='')
 lang='spa+eng' if 'spa' in available and 'eng' in available else ('spa' if 'spa' in available else 'eng')
 if 'spa' not in available:notes.append('OCR sin idioma español instalado: podría omitir nombres y etiquetas.')
 return engine.image_to_string(gray,lang=lang,config='--psm 6',timeout=35)

def parse_sat8409(text):
 """Lectura asistida del SAT-8409. No acredita permisos ni activa envíos.

 Las casillas de un documento escaneado suelen perder puntos o quedar unidas
 a las columnas anteriores. Sólo aceptar valores contextualizados por casilla.
 """
 clean=re.sub(r'[\t ]+', ' ', text).replace('–','-').replace('—','-')
 if not re.search(r'SAT\s*[- ]?8409|Importaci[oó]n Temporal con Reexportaci[oó]n',clean,re.I):
  return {}, []
 found={};notes=['Formulario SAT-8409 identificado. Todos los datos son sugerencias sujetas a revisión.']
 m=re.search(r'\bST\s*[-:/ ]\s*(20\d{2})\s*[-:/ ]\s*(\d{1,5})\b',clean,re.I)
 if m:found['declaration']=f'ST-{m.group(1)}-{int(m.group(2))}'
 # 2. Fecha: incluso si aparece pegada a la casilla 1.
 m=re.search(r'(?<!\d)2\s*[.:-]\s*Fecha\s*[:.]?\s*(\d{1,2}[/.-]\d{1,2}[/.-]20\d{2})',clean,re.I)
 if m:
  try:
   day,month,year=map(int,re.split(r'[/.-]',m.group(1)))
   found['start_date']=date(year,month,day).isoformat()
  except ValueError:notes.append('La fecha de la casilla 2 no es válida.')
 # 3. Titular = capitán en este tipo de documento, por criterio operativo SERVAMAR.
 # OCR puede confundir el 3 inicial con S, y poner el valor en la línea siguiente.
 m=re.search(r'(?:\b[3S5]\s*[.:-]\s*)?Nombres\s+y\s+apellidos\s+completos\s+del\s+titular\s+del\s+permiso\s*[:.]?\s*([^\r\n]*)',clean,re.I)
 if m:
  value=m.group(1).strip(' -:|_')
  if not value:
   tail=clean[m.end():].splitlines()
   value=next((line.strip(' -:|_') for line in tail if line.strip(' -:|_')), '')
  value=re.split(r'\s+(?:4\s*[.:-]|N[uú]mero\s+de\s+pasaporte)\b',value,flags=re.I)[0]
  value=re.sub(r'[^\w\s\-À-ÿ.]','',value).strip()
  if 3<=len(value)<=80 and not re.search(r'pasaporte|domicilio|expedici[oó]n',value,re.I):
   found['captain']=value
 # Casilla 23: los nombres entre comillas se deben reconocer aunque el OCR
 # agregue un paréntesis a "23", altere "embarcación" o una las columnas.
 # No inferir el nombre a partir de otras casillas.
 section_match=re.search(
  r'(?im)^\s*[\[(]?\s*23\s*[.:-]\s*[^\r\n]{0,115}',clean)
 if section_match:
  section=section_match.group(0)
  # Es más seguro leer el valor entre comillas que tomar el texto que sigue
  # a la etiqueta: la etiqueta puede estar unida a la aduana o a la casilla 24.
  quoted=re.search(r'[“\"«]\s*([A-ZÀ-Ý0-9][A-ZÀ-Ý0-9 .\-\']{1,70}?)\s*[”\"»]',section,re.I)
  if quoted:
   proposed=re.sub(r'\s+',' ',quoted.group(1)).strip(' .-')
   if proposed and not re.search(r'(?i)nombre|embarcaci[oó]n|cubiertas',proposed):found['name']=proposed
  if not found.get('name'):
   # Respaldo para permisos sin comillas: extraer después de la etiqueta y
   # truncar antes de la clasificación o de la siguiente casilla.
   tail=re.split(r'(?i)embarcaci[oó]n\s*[:.]?',section,maxsplit=1)
   if len(tail)==2:
    proposed=re.split(r'(?i)\s+(?:(?:24\s*[.:-])|VELERO|YATE|LANCHA|CATAMAR[AÁ]N|TRIMAR[AÁ]N|MOTONAVE|BARCO|BUQUE)\b',tail[1],maxsplit=1)[0]
    proposed=re.sub(r'\s+',' ',proposed).strip(' \"“”\'|_-')
    if 2<=len(proposed)<=70:found['name']=proposed
 # 23. Nombre; separar la clase de embarcación y evitar casilla 24.
 m=re.search(r'(?<!\d)23\s*[.:-]\s*Nombre\s+y\s+tipo\s+de\s+embarcaci[oó]n\s*[:.]?\s*([^\r\n]+)',clean,re.I)
 if m:
  value=re.split(r'\s+(?:24\s*[.:-]|VELERO|YATE|LANCHA|CATAMAR[AÁ]N|TRIMAR[AÁ]N|MOTONAVE|BARCO|BUQUE)\b',m.group(1),maxsplit=1,flags=re.I)[0]
  value=value.strip(" \"“”'_|" )
  if 2<=len(value)<=85 and not found.get('name'):found['name']=value
 # 26. Correo del titular en observaciones; requiere corroboración antes de usarlo.
 m=re.search(r'(?<!\d)26\s*[.:-]\s*Observaciones\s*[:.]?\s*([^\r\n]+)',clean,re.I)
 if m:
  e=re.search(r'\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b',m.group(1),re.I)
  if e:
   found['email']=e.group(0)
   notes.append('Correo de casilla 26 leído por OCR: comprueba carácter por carácter antes de guardarlo o enviar avisos.')
 # 31. Vencimiento: valor documental de referencia; no sustituir el cálculo hasta confirmar.
 m=re.search(r'(?<!\d)31\s*[.:-]\s*Fecha\s+de\s+expiraci[oó]n\s+de\s+la\s+permanencia\s*[:.]?\s*(\d{1,2}[/.-]\d{1,2}[/.-]20\d{2})',clean,re.I)
 if m:
  try:
   day,month,year=map(int,re.split(r'[/.-]',m.group(1)))
   expiry=date(year,month,day)
   found['documented_expiry']=expiry.isoformat()
   if 'start_date' in found:
    actual=date.fromisoformat(found['start_date'])
    msg='coincide con' if (expiry-actual).days==90 else 'NO coincide con'
    notes.append('Casilla 31: '+expiry.strftime('%d/%m/%Y')+'; '+msg+' el plazo de 90 días. Verifica el documento.')
   else:notes.append('Casilla 31: '+expiry.strftime('%d/%m/%Y')+'; falta confirmar el ingreso.')
  except ValueError:notes.append('La fecha de la casilla 31 no es válida.')
 if found.get('captain'):notes.append('Para SAT-8409 se sugiere el titular (casilla 3) como capitán, según el criterio de SERVAMAR.')
 return found,notes

def _sat8409_titular_en_casilla3(blob, suffix, notes):
 """Read *only* the value area of box 3 on the standard portrait SAT-8409.

 This is a fallback for scans whose table lines defeat full-page OCR. This
 region is used only when the SAT-8409 heading was detected in the full text.
 It returns a suggestion, not a certified identity.
 """
 try:
  import pytesseract
  from PIL import Image,ImageOps,ImageEnhance
  from io import BytesIO
  engine=_ocr_engine()
  if suffix=='.pdf':
   import fitz
   with fitz.open(stream=blob,filetype='pdf') as doc:
    if not doc: return None
    page=doc[0]
    # Standard portrait SAT-8409: box 3 lies just above passport field 4.
    if not (0.70<=page.rect.width/page.rect.height<=0.85):
     notes.append('Formato SAT-8409 no estándar: verifica manualmente el titular.')
     return None
    rect=page.rect
    region=fitz.Rect(rect.x0+rect.width*.04,rect.y0+rect.height*.142,
                     rect.x0+rect.width*.95,rect.y0+rect.height*.166)
    pix=page.get_pixmap(matrix=fitz.Matrix(4,4),clip=region,alpha=False)
    im=Image.open(BytesIO(pix.tobytes('png')))
  else:
   im=Image.open(BytesIO(blob)).convert('RGB')
   if not (0.68<=im.width/im.height<=0.90):
    notes.append('Imagen SAT-8409 no estándar: verifica manualmente el titular.')
    return None
   im=im.crop((int(im.width*.04),int(im.height*.142),int(im.width*.95),int(im.height*.166)))
   if im.width<1400:im=im.resize((im.width*3,im.height*3))
  gray=ImageEnhance.Contrast(ImageOps.grayscale(im)).enhance(1.8)
  available=engine.get_languages(config='')
  lang='spa+eng' if {'spa','eng'}<=set(available) else ('spa' if 'spa' in available else 'eng')
  raw=engine.image_to_string(gray,lang=lang,config='--psm 6',timeout=20)
  for row in raw.splitlines():
   line=re.sub(r'[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ .\-]',' ',row).strip(' .-')
   line=re.sub(r'\s+',' ',line)
   # Do not accept captions, labels, passport or other unrelated fields.
   if (4<=len(line)<=70 and len(line.split())>=2 and
       not re.search(r'(?i)nombre|apellido|titular|permiso|pasaporte|pa[ií]s|expedici[oó]n|domicilio|guatemala|fecha|n[uú]mero',line) and
       re.fullmatch(r'[A-Za-zÁÉÍÓÚÜÑáéíóúüñ .\-]+',line) and
       line.upper()==line):
    return line
 except Exception as exc:
  notes.append('No se pudo leer separadamente la casilla 3: '+str(exc)[:90])
 return None

def analyze_document(blob,suffix):
 """PDF digital: extraer texto; PDF escaneado: renderizar y aplicar OCR.
 Los campos extraídos son sugerencias y nunca autorizaciones definitivas.
 """
 notes=[];parts=[];pages_read=0;ocr_pages=0
 if suffix=='.pdf':
  try:
   import fitz
   from PIL import Image
   from io import BytesIO
   with fitz.open(stream=blob,filetype='pdf') as doc:
    if not 1<=len(doc)<=20:raise ValueError('PDF debe tener entre 1 y 20 páginas.')
    for page in list(doc)[:3]:
     pages_read+=1
     digital=page.get_text(sort=True).strip()
     if len(digital)>=80:
      parts.append(digital)
      continue
     try:
      engine=_ocr_engine()
      # 2.5x produce ~180 DPI on ordinary 72 DPI PDF pages.
      pix=page.get_pixmap(matrix=fitz.Matrix(2.5,2.5),alpha=False)
      if pix.width*pix.height>18_000_000:raise ValueError('La página excede el tamaño permitido para OCR.')
      with Image.open(BytesIO(pix.tobytes('png'))) as im:
       recognized=_ocr_image(im,engine,notes)
      parts.append(digital+'\n'+recognized)
      ocr_pages+=1
     except Exception as exc:
      notes.append('No fue posible leer la página escaneada '+str(pages_read)+': '+str(exc)[:200])
      if digital:parts.append(digital)
  except ValueError:raise
  except Exception as exc:notes.append('No se pudo abrir el PDF: '+str(exc)[:180])
 else:
  try:
   from PIL import Image
   from io import BytesIO
   engine=_ocr_engine()
   with Image.open(BytesIO(blob)) as im:parts.append(_ocr_image(im,engine,notes))
   ocr_pages=1;pages_read=1
  except Exception as exc:notes.append('OCR de imagen no disponible: '+str(exc)[:200])
 text='\n'.join(parts)[:50000]
 if ocr_pages:notes.append('Reconocimiento OCR aplicado a '+str(ocr_pages)+' página(s).')
 if suffix=='.pdf' and pages_read==3:notes.append('Solo se analizaron las tres primeras páginas.')
 guesses={};candidates={}
 sat_fields,sat_notes=parse_sat8409(text)
 guesses.update(sat_fields);notes.extend(sat_notes)
 if sat_fields and not guesses.get('captain'):
  regional=_sat8409_titular_en_casilla3(blob,suffix,notes)
  if regional:
   guesses['captain']=regional
   notes.append('Titular/capitán sugerido desde la casilla 3; confirma el nombre antes de guardarlo.')
  else:
   notes.append('No se pudo identificar el titular de la casilla 3; escribe el capitán manualmente.')
 # El número puede estar separado por guiones, espacios o saltos de línea.
 match=re.search(r'\bST\s*[-–—:/ ]\s*(20\d{2})\s*[-–—:/ ]\s*(\d{1,5})\b',text,re.I)
 if match:guesses['declaration']=f'ST-{match.group(1)}-{int(match.group(2))}'
 lines=[re.sub(r'\s+',' ',ln).strip() for ln in text.splitlines() if ln.strip()]
 def candidate_value(i,label_pattern):
  line=lines[i]
  m=re.search(label_pattern+r'\s*[:\-–]?\s*(.*)$',line,re.I)
  if not m:return None
  value=m.group(1).strip(' :—–-')
  if not value and i+1<len(lines):value=lines[i+1]
  return value.strip()
 for i,ln in enumerate(lines):
  if re.search(r'\b(?:fecha\s+de\s+)?(?:ingreso|entrada|arribo)\b',ln,re.I):
   search_line=ln+' '+(lines[i+1] if i+1<len(lines) else '')
   m=re.search(r'\b(\d{1,2})[/-](\d{1,2})[/-](20\d{2})\b',search_line)
   if m:
    try:candidates.setdefault('start_date',[]).append(date(int(m.group(3)),int(m.group(2)),int(m.group(1))).isoformat())
    except ValueError:pass
  name=candidate_value(i,r'(?:nombre\s+de\s+la\s+embarcaci[oó]n|embarcaci[oó]n|nombre\s+del\s+(?:barco|yate|buque))')
  if name and 2<=len(name)<=85 and not re.search(r'\b(permiso|fecha|ingreso|capit[aá]n)\b',name,re.I):candidates.setdefault('name',[]).append(name)
  captain=candidate_value(i,r'(?:nombre\s+del\s+capit[aá]n|capit[aá]n)')
  if captain and 2<=len(captain)<=85 and not re.search(r'\b(permiso|fecha|ingreso|embarcaci[oó]n)\b',captain,re.I):candidates.setdefault('captain',[]).append(captain)
 for k,vals in candidates.items():
  unique=set(vals)
  if len(unique)==1 and k not in guesses and not (sat_fields and k in ('name','captain','start_date')):guesses[k]=vals[0]
  elif len(unique)>1 and k not in sat_fields and not (sat_fields and k in ('name','captain','start_date')):notes.append('Se encontraron varios valores posibles para '+k+'; revisa el documento.')
 if not text.strip():notes.append('No se encontró texto legible. Verifica que Tesseract OCR esté instalado y que el permiso no esté protegido.')
 elif not guesses:notes.append('Se reconoció texto, pero no se identificaron los campos; necesitamos adaptar las etiquetas al formato de tu permiso.')
 notes.append('Comprueba siempre todos los datos sugeridos antes de guardar.')
 return guesses,notes

def save_document_for_vessel(c,vessel_id,token):
 if not re.fullmatch(r'[0-9a-f]{32}',str(token)):raise ValueError('Documento provisional inválido.')
 path=next((p for p in PENDING_DIR.glob(token+'.*') if p.is_file()),None)
 if path is None:raise ValueError('Documento provisional no encontrado; vuelve a cargarlo.')
 blob=path.read_bytes();digest=hashlib.sha256(blob).hexdigest();suffix=path.suffix
 if c.execute('SELECT id FROM permit_documents WHERE vessel_id=? AND sha256=?',(vessel_id,digest)).fetchone():
  path.unlink(missing_ok=True);return
 DOC_DIR.mkdir(exist_ok=True,parents=True)
 storage=uuid.uuid4().hex+suffix;shutil_path=DOC_DIR/storage
 shutil_path.write_bytes(blob)
 c.execute('INSERT INTO permit_documents(vessel_id,file_name,storage_name,mime,sha256) VALUES(?,?,?,?,?)',(vessel_id,'permiso'+suffix,storage,ALLOWED_DOCS[suffix],digest))
 path.unlink(missing_ok=True)

@app.post('/api/documents/analyze')
def document_analyze():
 f=request.files.get('file')
 if not f:return jsonify(error='Selecciona una imagen o PDF del permiso.'),400
 try:
  filename,suffix,blob=safe_uploaded_document(f)
  guesses,notes=analyze_document(blob,suffix)
  PENDING_DIR.mkdir(exist_ok=True,parents=True)
  token=uuid.uuid4().hex
  (PENDING_DIR/(token+suffix)).write_bytes(blob)
 except ValueError as exc:return jsonify(error=str(exc)),400
 confidence={k:('revisar' if k in ('captain','email') else 'reconocido') for k in guesses if k in ('declaration','name','captain','email','start_date')}
 return jsonify(token=token,filename=filename,fields=guesses,notes=notes,recognized=bool(guesses),field_status=confidence)

@app.post('/api/vessels/new')
def create_vessel():
 data=request.get_json(silent=True) or {}
 name=str(data.get('name','')).strip();declaration=str(data.get('declaration','')).strip();captain=str(data.get('captain','')).strip();registration=str(data.get('registration_number','')).strip().upper()
 start=requiredate(data.get('start_date'));email=str(data.get('email','')).strip();notes=str(data.get('notes','')).strip()
 if not name or not declaration or not start:return jsonify(error='Nombre, ST y fecha de ingreso son obligatorios.'),400
 if any(len(x)>200 for x in (name,declaration,captain,email,registration)) or len(notes)>2000:return jsonify(error='Uno de los datos supera el límite permitido.'),400
 if start>date.today():return jsonify(error='La fecha de ingreso no puede estar en el futuro.'),400
 if email and ('@' not in email or len(email)>200):return jsonify(error='Correo del cliente inválido.'),400
 token=str(data.get('document_token') or '')
 if token and (not re.fullmatch(r'[0-9a-f]{32}',token) or not list(PENDING_DIR.glob(token+'.*'))):return jsonify(error='Vuelve a cargar el documento; no se encontró.'),400
 expiry=start+timedelta(days=90)
 with lock,conn() as c:
  matches=c.execute('SELECT id,name,declaration FROM vessels WHERE lower(trim(declaration))=lower(?)',(declaration,)).fetchall()
  if matches:return jsonify(error='Ya existe al menos un expediente con este número ST. Revísalo antes de crear otro.',existing=[dict(x) for x in matches]),409
  c.execute('INSERT INTO vessels(declaration,name,captain,email,stage,start_date,expiry_date,validated,notes,registration_number) VALUES(?,?,?,?,?,?,?,?,?,?)',(declaration,name,captain,email,'ingreso',start.isoformat(),expiry.isoformat(),1,notes,registration))
  vessel_id=c.execute('SELECT last_insert_rowid()').fetchone()[0]
  c.execute('INSERT INTO history(vessel_id,kind,event_date,expiry_date,description) VALUES(?,?,?,?,?)',(vessel_id,'ingreso',start.isoformat(),expiry.isoformat(),'Ingreso manual confirmado por el usuario; verificar soporte documental.' if not token else 'Ingreso manual con documento adjunto; datos revisados por el usuario.'))
  c.executemany('INSERT INTO alert_settings(vessel_id,days_before) VALUES(?,?)',[(vessel_id,30),(vessel_id,15),(vessel_id,1)])
  if token:save_document_for_vessel(c,vessel_id,token)
 return jsonify(ok=True,id=vessel_id,expiry_date=expiry.isoformat()),201

@app.post('/api/vessels/<int:id>/document')
def attach_document(id):
 f=request.files.get('file')
 if not f:return jsonify(error='Selecciona un documento.'),400
 try:
  _,suffix,blob=safe_uploaded_document(f)
  PENDING_DIR.mkdir(parents=True,exist_ok=True);token=uuid.uuid4().hex
  (PENDING_DIR/(token+suffix)).write_bytes(blob)
  with lock,conn() as c:
   if not c.execute('SELECT 1 FROM vessels WHERE id=?',(id,)).fetchone():return jsonify(error='Expediente no encontrado.'),404
   save_document_for_vessel(c,id,token)
 except ValueError as exc:return jsonify(error=str(exc)),400
 return jsonify(ok=True)

@app.get('/api/vessels/<int:id>/documents')
def list_documents(id):
 with conn() as c:
  if not c.execute('SELECT 1 FROM vessels WHERE id=?',(id,)).fetchone():return jsonify(error='Expediente no encontrado.'),404
  rows=c.execute('SELECT id,file_name,uploaded_at,sha256 FROM permit_documents WHERE vessel_id=? ORDER BY id DESC',(id,)).fetchall()
 return jsonify([dict(x) for x in rows])

@app.get('/api/documents/<int:docid>/download')
def download_document(docid):
 with conn() as c:
  row=c.execute('SELECT * FROM permit_documents WHERE id=?',(docid,)).fetchone()
 if not row:abort(404)
 path=DOC_DIR/row['storage_name']
 if not path.is_file():abort(404)
 return send_file(path,mimetype=row['mime'],as_attachment=True,download_name=row['file_name'])

@app.get('/api/vessels')
def vessels():
 """Search present vessel data and historical movement dates without changing records."""
 q=request.args.get('q','').strip()
 captain=request.args.get('captain','').strip()
 vessel_name=request.args.get('vessel_name','').strip()
 registration=request.args.get('registration_number','').strip()
 if len(q)>200 or len(captain)>200 or len(vessel_name)>200 or len(registration)>200:return jsonify(error='Búsqueda demasiado larga'),400
 try:limit=min(max(int(request.args.get('limit',120)),1),500)
 except ValueError:return jsonify(error='Límite inválido'),400
 where=[];params=[]
 if q:
  where.append('(v.declaration LIKE ? OR v.name LIKE ? OR v.captain LIKE ?)')
  params.extend(['%'+q+'%']*3)
 if captain:
  where.append('v.captain LIKE ?');params.append('%'+captain+'%')
 if vessel_name:
  where.append('v.name LIKE ?');params.append('%'+vessel_name+'%')
 if registration:
  where.append('v.registration_number LIKE ?');params.append('%'+registration+'%')
 # The entered month/year is intentionally independent of current status and
 # includes dates recorded against older movements, even unvalidated history.
 for kind,column,history_column in [('entry','start_date','event_date'),('expiry','expiry_date','expiry_date')]:
  exact=request.args.get(kind+'_date','').strip()
  month=request.args.get(kind+'_month','').strip()
  if exact and month:return jsonify(error='Selecciona fecha exacta O mes en '+kind),400
  if exact:
   d=requiredate(exact)
   if not d or d.isoformat()!=exact:return jsonify(error='Fecha inválida: '+kind),400
   where.append(f'(v.{column}=? OR EXISTS (SELECT 1 FROM history h WHERE h.vessel_id=v.id AND h.{history_column}=? AND '+ ("h.kind='ingreso'" if kind=='entry' else '1=1') +'))')
   params.extend((exact,exact))
  elif month:
   if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])',month):return jsonify(error='Mes inválido: '+kind),400
   pattern=month+'%'
   where.append(f'(v.{column} LIKE ? OR EXISTS (SELECT 1 FROM history h WHERE h.vessel_id=v.id AND h.{history_column} LIKE ? AND '+ ("h.kind='ingreso'" if kind=='entry' else '1=1') +'))')
   params.extend((pattern,pattern))
 clause=' WHERE '+' AND '.join(where) if where else ''
 with conn() as c:
  total=c.execute('SELECT count(*) FROM vessels v'+clause,params).fetchone()[0]
  rows=c.execute("""SELECT v.*, (SELECT MIN(h.event_date) FROM history h
    WHERE h.vessel_id=v.id AND h.kind='ingreso' AND h.event_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]') AS first_entry_date
    FROM vessels v"""+clause,params).fetchall()
  # Aplicar el vencimiento operativo o la referencia histórica identificada
  # por el mismo motor que alimenta el panel de vencimientos. Los expedientes
  # cerrados/no determinables no reciben una fecha vigente ficticia.
  deadlines={item['id']:item for item in current_deadlines()}
  # Fecha del último movimiento consignado, no de la primera entrada.
  # Usar fecha real del historial; no fabricar fecha para cierres inferidos.
  vessel_ids=[row['id'] for row in rows]
  last_movements={}
  if vessel_ids:
   for offset in range(0,len(vessel_ids),700):
    batch=vessel_ids[offset:offset+700]
    sql='SELECT vessel_id,kind,event_date,id,description FROM history WHERE vessel_id IN ('+','.join('?' for _ in batch)+')'
    for h in c.execute(sql,batch):
     d=requiredate(h['event_date'])
     if not d and h['kind'] in HISTORICAL_TEMPORARY_KINDS:
      d=historical_temporary_date(h['kind'],h['description'])
     if not d and h['kind']=='salida_archivo':
      m=re.search(r'\bCIERRE\s+DE\s+PERMISO\b\s*[:\-]?\s*(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b',str(h['description'] or ''),re.I)
      if m:
       try:d=date(int(m.group(3)),int(m.group(2)),int(m.group(1)))
       except ValueError:pass
     if d:
      candidate=(d.isoformat(),h['id'])
      old=last_movements.get(h['vessel_id'])
      if old is None or candidate>old[0]:
       last_movements[h['vessel_id']]=(candidate,h['kind'])
  enriched=[]
  for row in rows:
   entry=serialize(row)
   current=deadlines.get(entry['id'])
   entry['current_expiry_date']=current['expiry_date'] if current else None
   entry['current_stage']=('Permiso cerrado' if current and current.get('closure_due_to_90_days') else 'Salida temporal' if current and current['temporarily_away'] else current['stage'] if current else ('Permiso cerrado' if entry['stage']=='cierre' else entry['stage']))
   entry['current_status']=current['status'] if current else (('Permiso cerrado — 90 días fuera cumplidos' if entry.get('closure_reason')=='salida temporal sin retorno' else 'Permiso cerrado — cierre registrado') if entry['stage']=='cierre' else 'Sin vencimiento')
   entry['current_date_quality']=current['date_quality'] if current else 'sin vencimiento vigente'
   last=last_movements.get(entry['id'])
   entry['last_movement_date']=last[0][0] if last else None
   entry['last_movement_type']=last[1] if last else None
   # Compartir con la UI el estado real del contador temporal.
   # Los cierres explícitos se mantienen cerrados aunque no tengan un plazo vigente.
   exit_info=temporary_exit_summary(c,entry['id'])
   archived_closure=historical_documented_closure(c,entry['id'])
   entry['archived_closure_date']=archived_closure.isoformat() if archived_closure else None
   closed=entry['stage']=='cierre' or bool(archived_closure) or bool(current and current.get('closure_due_to_90_days')) or exit_info['must_close']
   entry['display_stage']=('Permiso Cerrado' if closed else
      'Salida Temporal' if exit_info['currently_away'] else
      {'ingreso':'Ingreso 3 meses','ampliacion':'Ampliación 9 meses',
       'deposito':'Depósito 12 meses'}.get(current['stage'] if current else entry['stage'],'Sin etapa'))
   entry['days_out']=exit_info['current_days_away'] if exit_info['currently_away'] else None
   entry['return_deadline']=exit_info['return_deadline']
   entry['remaining_days']=current['remaining_days'] if current else None
   # Cierre manual sin una salida registrada: no inferir 90 días inexistentes.
   enriched.append(entry)
  # Ordenar la totalidad ANTES de aplicar el límite de 120 resultados.
  rows=sorted(enriched,key=search_deadline_sort_key)[:limit]
 return jsonify({'total':total,'items':rows})
def registration_related(c,id,registration):
 """Return other permits linked by an explicitly supplied registration number."""
 number=(registration or '').strip()
 if not number:return []
 return [dict(x) for x in c.execute('SELECT id,declaration,name,registration_number FROM vessels WHERE registration_number=? COLLATE NOCASE AND id<>? ORDER BY id DESC LIMIT 100',(number,id)).fetchall()]

@app.get('/api/vessels/<int:id>')
def detail(id):
 with conn() as c:
  v=c.execute('SELECT * FROM vessels WHERE id=?',(id,)).fetchone()
  if not v:return jsonify(error='No existe'),404
  h=c.execute('SELECT * FROM history WHERE vessel_id=? ORDER BY id DESC',(id,)).fetchall()
  days=c.execute('SELECT days_before FROM alert_settings WHERE vessel_id=? AND enabled=1 ORDER BY days_before DESC',(id,)).fetchall()
  logs=c.execute('SELECT * FROM alert_log WHERE vessel_id=? ORDER BY id DESC LIMIT 50',(id,)).fetchall()
 closure_date=historical_documented_closure(c,id)
 exit_info=temporary_exit_summary(c,id)
 if closure_date:
  exit_info['currently_away']=False
  exit_info['return_days_left']=None
  exit_info['note']='Cierre de permiso anotado en el historial: '+closure_date.strftime('%d/%m/%Y')
 if v['stage']=='cierre' and exit_info['currently_away']:
  exit_info['currently_away']=False
  exit_info['return_days_left']=None
  exit_info['note']='El permiso ya fue cerrado. La salida previa no se considera temporal activa.'
 return jsonify({'vessel':serialize(v),'history':[serialize(r) for r in h],'days':[r[0] for r in days],'logs':[serialize(r) for r in logs], 'current_deadline':next((x for x in current_deadlines() if x['id']==id),None), 'temporary_exit':exit_info, 'reentry_eligible_date':v['reentry_eligible_date'], 'related_registration':registration_related(c,id,v['registration_number']), 'archived_closure_date':closure_date.isoformat() if closure_date else None})
@app.post('/api/vessels/<int:id>')
def update(id):
 data=request.get_json(force=True)
 email=str(data.get('email','')).strip()
 if email and ('@' not in email or len(email)>254):return jsonify(error='Correo no válido'),400
 days=data.get('days',[30,15,1]);
 if not isinstance(days,list) or len(days)>20 or any(type(x) is not int or x<1 or x>365 for x in days):return jsonify(error='Días no válidos'),400
 with lock,conn() as c:
  old=c.execute('SELECT * FROM vessels WHERE id=?',(id,)).fetchone()
  if not old:return jsonify(error='No existe'),404
  # La ficha mantiene su ID; las relaciones con historial y avisos no cambian.
  name=str(data.get('name',old['name']) or '').strip()
  declaration=str(data.get('declaration',old['declaration']) or '').strip()
  captain=str(data.get('captain',old['captain']) or '').strip()
  registration=str(data.get('registration_number',old['registration_number']) or '').strip().upper()
  if not name or not declaration:return jsonify(error='Nombre y declaración ST son obligatorios'),400
  if any(len(x)>200 for x in (name,declaration,captain,registration)):return jsonify(error='Nombre, declaración, registro o capitán demasiado largos'),400
  different=c.execute('SELECT id FROM vessels WHERE declaration=? AND name=? AND id<>?',(declaration,name,id)).fetchone()
  if different:return jsonify(error='Ya existe otra ficha con la misma declaración y nombre. Revisa antes de modificar para evitar duplicados.'),409
  notes=str(data.get('notes',''))[:4000]
  fields={'name':name,'declaration':declaration,'captain':captain,'registration_number':registration,'email':email,'notes':notes,'client_opt_in':int(bool(data.get('client_opt_in',False))),'client_send_approved':int(bool(data.get('client_send_approved',False)))}
  changed={k:{'antes':old[k], 'despues':v} for k,v in fields.items() if old[k]!=v}
  try:
   c.execute('UPDATE vessels SET name=?,declaration=?,captain=?,registration_number=?,email=?,client_opt_in=?,client_send_approved=?,notes=? WHERE id=?',(name,declaration,captain,registration,email,fields['client_opt_in'],fields['client_send_approved'],notes,id))
   c.execute('DELETE FROM alert_settings WHERE vessel_id=?',(id,))
   c.executemany('INSERT INTO alert_settings(vessel_id,days_before) VALUES(?,?)',[(id,x) for x in sorted(set(days))])
   if changed:c.execute('INSERT INTO edit_audit(vessel_id,changes) VALUES(?,?)',(id,json.dumps(changed,ensure_ascii=False)))
  except sqlite3.IntegrityError:return jsonify(error='La modificación entra en conflicto con otro expediente'),409
 return jsonify(ok=True,updated_fields=list(changed))
@app.get('/api/vessels/<int:id>/edits')
def edits(id):
 with conn() as c:
  if not c.execute('SELECT 1 FROM vessels WHERE id=?',(id,)).fetchone():return jsonify(error='No existe'),404
  rows=c.execute('SELECT changed_at,changes FROM edit_audit WHERE vessel_id=? ORDER BY id DESC LIMIT 50',(id,)).fetchall()
 return jsonify([{'changed_at':r['changed_at'],'changes':json.loads(r['changes'])} for r in rows])
@app.post('/api/vessels/<int:id>/event')
def event(id):
 data=request.get_json(force=True)
 kind=data.get('kind');start=requiredate(data.get('start_date'))
 if kind not in ('ingreso','ampliacion','deposito','salida','retorno','cierre'):return jsonify(error='Tipo de movimiento no válido'),400
 if kind!='ampliacion' and not start:return jsonify(error='Fecha del movimiento obligatoria (dd/mm/yyyy)'),400
 if data.get('start_date') and not start:return jsonify(error='Fecha inválida (dd/mm/yyyy)'),400
 if start and start>date.today():return jsonify(error='No se puede confirmar un movimiento con fecha futura.'),400
 with lock,conn() as c:
  v=c.execute('SELECT * FROM vessels WHERE id=?',(id,)).fetchone()
  if not v:return jsonify(error='No existe'),404
  try:expiry,basis=calculate_movement(c,v,kind,start)
  except ValueError as e:return jsonify(error=str(e)),400
  # No aceptar una fecha calculada desde el navegador: el servidor la calcula de nuevo.
  if kind=='deposito' and not data.get('start_date'):
   return jsonify(error='Indica la fecha efectiva de ingreso a depósito'),400
  description=str(data.get('description','')).strip()[:850]
  full_description=(description+(' | Fecha de autorización no consignada.' if kind=='ampliacion' and not start else '')+' | Cálculo: '+basis)[:1000]
  c.execute('INSERT INTO history(vessel_id,kind,event_date,expiry_date,description) VALUES(?,?,?,?,?)',
            (id,kind,start.isoformat() if start else '',expiry.isoformat() if expiry else '',full_description))
  new_history_id=c.execute('SELECT last_insert_rowid()').fetchone()[0]
  c.execute('INSERT INTO movement_before_state(history_id,vessel_id,state_json) VALUES(?,?,?)',
            (new_history_id,id,json.dumps(dict(v),ensure_ascii=False)))
  if kind in ('salida','retorno') and v['stage']=='revision':
   ctx=movement_context(c,v)
   c.execute('UPDATE vessels SET stage=?,validated=1,expiry_date=? WHERE id=?',(ctx['stage'],ctx['expiry_date'],id))
  if kind=='retorno':
   # Sumar solo los días de esta salida, una sola vez, tras registrarla.
   c.execute('UPDATE vessels SET expiry_date=? WHERE id=?',(expiry.isoformat(),id))
  elif kind=='cierre':
   c.execute("""UPDATE vessels SET stage='cierre',validated=1,expiry_date='',
             closure_date=?,reentry_eligible_date=?,closure_reason='salida definitiva documentada'
             WHERE id=?""",(start.isoformat(),(start+timedelta(days=90)).isoformat(),id))
  elif kind=='ampliacion':
   # La autorización no cambia la fecha de ingreso original del permiso.
   c.execute("""UPDATE vessels SET stage='ampliacion',expiry_date=?,validated=1,
                closure_date=NULL,reentry_eligible_date=NULL,closure_reason=NULL WHERE id=?""",(expiry.isoformat(),id))
  elif kind in ('ingreso','deposito'):
   c.execute("""UPDATE vessels SET stage=?,start_date=?,expiry_date=?,validated=1,
                closure_date=NULL,reentry_eligible_date=NULL,closure_reason=NULL WHERE id=?""",
             (kind,start.isoformat(),expiry.isoformat(),id))
 return jsonify(ok=True,expiry_date=expiry.isoformat() if expiry else '',basis=basis)
# V32: corrección controlada de movimientos ingresados manualmente.
# No se borra la información fuente importada; el borrado queda registrado en auditoría.
def previous_manual_state(c,vessel,history_id):
    """Compatibilidad con movimientos V31 sin instantánea previa.
    Recupera la última etapa que modifica el vencimiento, o vuelve al historial importado.
    """
    rows=c.execute("SELECT * FROM history WHERE vessel_id=? AND id<? ORDER BY id",(vessel['id'],history_id)).fetchall()
    historical=[r for r in rows if r['source_id'] is not None and r['kind'] in ('ingreso','ampliacion_archivo','deposito_archivo') and requiredate(r['expiry_date'])]
    base=max(historical,key=lambda r:(r['expiry_date'],r['id'])) if historical else None
    start=min((r['event_date'] for r in rows if r['kind']=='ingreso' and requiredate(r['event_date'])),default=vessel['start_date'] or '')
    state={'stage':({'ingreso':'ingreso','ampliacion_archivo':'ampliacion','deposito_archivo':'deposito'}.get(base['kind'],'revision') if base else 'revision'),'expiry_date':base['expiry_date'] if base else '',
           'start_date':start,'validated':1, 'closure_date':None,
           'reentry_eligible_date':None,'closure_reason':None}
    for r in rows:
        if r['source_id'] is not None:continue
        if r['kind'] in ('ingreso','ampliacion','deposito'):
            state['stage']=r['kind'];state['expiry_date']=r['expiry_date'] or ''
            if r['kind'] in ('ingreso','deposito'):state['start_date']=r['event_date'] or state['start_date']
            state['closure_date']=state['reentry_eligible_date']=state['closure_reason']=None
        elif r['kind']=='retorno':
            state['expiry_date']=r['expiry_date'] or state['expiry_date']
        elif r['kind'] in ('cierre','cierre_automatico'):
            d=requiredate(r['event_date'])
            state.update(stage='cierre',expiry_date='',closure_date=r['event_date'],
                reentry_eligible_date=(d+timedelta(days=90)).isoformat() if d else None,
                closure_reason='salida definitiva documentada' if r['kind']=='cierre' else 'salida temporal sin retorno')
    return state

@app.post('/api/vessels/<int:id>/history/<int:history_id>/delete')
def delete_manual_movement(id,history_id):
    payload=request.get_json(silent=True) or {}
    if payload.get('confirmation')!='ELIMINAR MOVIMIENTO':
        return jsonify(error='Debes confirmar expresamente la eliminación del movimiento.'),400
    with lock,conn() as c:
        v=c.execute('SELECT * FROM vessels WHERE id=?',(id,)).fetchone()
        if not v:return jsonify(error='Expediente no encontrado.'),404
        r=c.execute('SELECT * FROM history WHERE id=? AND vessel_id=?',(history_id,id)).fetchone()
        if not r:return jsonify(error='Movimiento no encontrado.'),404
        if r['source_id'] is not None or r['kind'] not in ('ingreso','ampliacion','deposito','salida','retorno','cierre'):
            return jsonify(error='Los movimientos importados y los cierres automáticos están protegidos. Solo pueden eliminarse movimientos introducidos manualmente.'),400
        later=c.execute('SELECT id,kind FROM history WHERE vessel_id=? AND id>? ORDER BY id LIMIT 1',(id,history_id)).fetchone()
        if later:
            return jsonify(error='Primero elimina el movimiento posterior ('+str(later['kind'])+'). Se debe corregir el historial en orden inverso para no alterar cálculos dependientes.'),409
        earlier=c.execute('SELECT COUNT(*) FROM history WHERE vessel_id=? AND id<?',(id,history_id)).fetchone()[0]
        if r['kind']=='ingreso' and not earlier:
            return jsonify(error='Es el único ingreso que origina esta ficha. Para borrar una embarcación de prueba, usa la herramienta de limpieza de fichas, no este control.'),409
        snap=c.execute('SELECT state_json FROM movement_before_state WHERE history_id=?',(history_id,)).fetchone()
        before=json.loads(snap['state_json']) if snap else previous_manual_state(c,v,history_id)
        allowed=('stage','start_date','expiry_date','validated','closure_date','reentry_eligible_date','closure_reason')
        state={k:before.get(k) for k in allowed}
        if state['stage'] not in ('revision','ingreso','ampliacion','deposito','cierre'):
            return jsonify(error='No se pudo recuperar el estado anterior de manera segura.'),409
        # Respaldo íntegro antes de borrar cualquier dato; no se incluyen credenciales.
        backup_dir=DATA_DIR/'backups';backup_dir.mkdir(parents=True,exist_ok=True)
        backup_name='antes_eliminar_movimiento_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.sqlite3'
        backup_path=backup_dir/backup_name
        with sqlite3.connect(backup_path) as b:c.backup(b)
        try:
            c.execute('INSERT INTO movement_deletion_audit(vessel_id,deleted_history_id,deleted_row_json,previous_state_json,backup_name) VALUES(?,?,?,?,?)',
                (id,history_id,json.dumps(dict(r),ensure_ascii=False),json.dumps(state,ensure_ascii=False),backup_name))
            c.execute('DELETE FROM movement_before_state WHERE history_id=?',(history_id,))
            c.execute('DELETE FROM history WHERE id=? AND vessel_id=?',(history_id,id))
            c.execute('UPDATE vessels SET '+','.join(k+'=?' for k in allowed)+' WHERE id=?',
                tuple(state[k] for k in allowed)+(id,))
        except Exception:
            raise
    return jsonify(ok=True,message='Movimiento eliminado; vencimiento y estado restaurados al momento anterior.',backup=backup_name)

# V44: correcciones directas del historial. La fuente original se conserva en auditoría,
# los cambios de fecha se recalculan cuando la edición altera el estado del permiso.
@app.post('/api/vessels/<int:id>/history/<int:history_id>/edit')
def edit_movement(id, history_id):
 data=request.get_json(silent=True) or {}
 if data.get('confirmation')!='MODIFICAR MOVIMIENTO':
  return jsonify(error='Confirma la modificación del movimiento.'),400
 with lock,conn() as c:
  v=c.execute('SELECT * FROM vessels WHERE id=?',(id,)).fetchone()
  r=c.execute('SELECT * FROM history WHERE id=? AND vessel_id=?',(history_id,id)).fetchone()
  if not v or not r:return jsonify(error='No se encontró el expediente o movimiento.'),404
  raw_date=str(data.get('event_date','')).strip()
  new_date=requiredate(raw_date) if raw_date else None
  if raw_date and not new_date:return jsonify(error='Fecha inválida. Usa dd/mm/yyyy.'),400
  if new_date and new_date>date.today():return jsonify(error='La fecha del movimiento no puede ser futura.'),400
  description=str(data.get('description',r['description'] or '')).strip()[:1000]
  new_kind=str(data.get('kind',r['kind']))
  if new_kind!=r['kind']:
   return jsonify(error='Para cambiar el tipo de un movimiento, registra la corrección como un movimiento nuevo. La fecha y las observaciones sí pueden editarse.'),400
  # Una ampliación puede carecer de fecha. El resto requiere fecha para el cálculo.
  if new_kind in ('ingreso','deposito','salida','retorno','cierre') and not new_date:
   return jsonify(error='Este movimiento necesita una fecha válida.'),400
  changes={'event_date':{'antes':r['event_date'],'despues':new_date.isoformat() if new_date else ''},
           'description':{'antes':r['description'],'despues':description}}
  if (r['event_date'] or '')==(new_date.isoformat() if new_date else '') and (r['description'] or '')==description:
   return jsonify(ok=True,message='No había cambios que guardar.')
  later_manual=c.execute("SELECT id,kind FROM history WHERE vessel_id=? AND id>? AND source_id IS NULL AND kind IN ('ingreso','ampliacion','deposito','salida','retorno','cierre') ORDER BY id LIMIT 1",(id,history_id)).fetchone()
  # Si existe un movimiento posterior, no alterar el vencimiento consolidado sin recalcularlo.
  # Se permite corregir la observación; la fecha puede editarse y se marca una advertencia.
  recalc_manual=r['source_id'] is None and new_kind in ('ingreso','ampliacion','deposito','salida','retorno','cierre') and later_manual is None
  snapshot=c.execute('SELECT state_json FROM movement_before_state WHERE history_id=?',(history_id,)).fetchone() if recalc_manual else None
  before=json.loads(snapshot['state_json']) if snapshot else (previous_manual_state(c,v,history_id) if recalc_manual else None)
  # V45: al cambiar la fecha de una salida importada, comprobar si ya existe
  # un retorno manual dependiente. En ese caso hay que actualizar tanto ese
  # retorno como el vencimiento consolidado; nunca dejar cálculos antiguos.
  linked_return=None
  old_dep=requiredate(r['event_date'])
  if new_kind in ('salida','salida_archivo') and old_dep and new_date and new_date!=old_dep:
   following=c.execute("SELECT * FROM history WHERE vessel_id=? AND id>? AND kind IN ('retorno','retorno_archivo','salida','salida_archivo','ampliacion','deposito','ingreso','cierre') ORDER BY id",(id,history_id)).fetchall()
   if following and following[0]['kind']=='retorno' and following[0]['source_id'] is None:
    linked_return=following[0]
    next_ops=following[1:]
    if next_ops:
     return jsonify(error='Existe otro movimiento posterior al retorno. Corrígelo antes de editar esta salida, para evitar vencimientos inconsistentes.'),409
    rd=requiredate(linked_return['event_date'])
    if not rd or rd<new_date or (rd-new_date).days>=90:
     return jsonify(error='La nueva fecha es incompatible con el retorno registrado. Corrige primero el retorno o revisa las fechas.'),409
    old_days=(rd-old_dep).days;new_days=(rd-new_date).days
    if old_days<0 or old_days>=90:
     return jsonify(error='El retorno anterior tiene un plazo inconsistente. Revisa los movimientos antes de cambiar la salida.'),409
    recorded_old=requiredate(linked_return['expiry_date'])
    current_expiry=requiredate(v['expiry_date'])
    if not recorded_old or not current_expiry or current_expiry!=recorded_old:
     return jsonify(error='No se pudo identificar de forma segura el vencimiento del retorno posterior. No se modificó ningún movimiento.'),409
  backup_dir=DATA_DIR/'backups';backup_dir.mkdir(parents=True,exist_ok=True)
  backup_name='antes_modificar_movimiento_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.sqlite3'
  with sqlite3.connect(backup_dir/backup_name) as b:c.backup(b)
  # El movimiento se retira temporalmente dentro de la transacción para evitar
  # que la fecha anterior se utilice como salida/retorno durante el cálculo.
  if recalc_manual:
   c.execute('DELETE FROM movement_before_state WHERE history_id=?',(history_id,))
   c.execute('DELETE FROM history WHERE id=?',(history_id,))
   prior=dict(v)
   for key in ('stage','start_date','expiry_date','validated','closure_date','reentry_eligible_date','closure_reason'):
    if key in before:prior[key]=before[key]
   try:
    expiry,basis=calculate_movement(c,prior,new_kind,new_date)
   except ValueError as e:
    c.rollback()
    return jsonify(error='La corrección no se pudo calcular: '+str(e)),400
   c.execute('INSERT INTO history(id,vessel_id,source_id,kind,event_date,expiry_date,description,created_at) VALUES(?,?,?,?,?,?,?,?)',
    (history_id,id,r['source_id'],new_kind,new_date.isoformat() if new_date else '',expiry.isoformat() if expiry else '',description+' | Cálculo: '+basis,r['created_at']))
   c.execute('INSERT INTO movement_before_state(history_id,vessel_id,state_json) VALUES(?,?,?)',
    (history_id,id,json.dumps(before,ensure_ascii=False)))
   state={k:prior.get(k) for k in ('stage','start_date','expiry_date','validated','closure_date','reentry_eligible_date','closure_reason')}
   if new_kind=='retorno':state['expiry_date']=expiry.isoformat()
   elif new_kind=='cierre':state.update(stage='cierre',validated=1,expiry_date='',closure_date=new_date.isoformat(),reentry_eligible_date=(new_date+timedelta(days=90)).isoformat(),closure_reason='salida definitiva documentada')
   elif new_kind=='ampliacion':state.update(stage='ampliacion',validated=1,expiry_date=expiry.isoformat(),closure_date=None,reentry_eligible_date=None,closure_reason=None)
   elif new_kind in ('ingreso','deposito'):state.update(stage=new_kind,start_date=new_date.isoformat(),expiry_date=expiry.isoformat(),validated=1,closure_date=None,reentry_eligible_date=None,closure_reason=None)
   elif new_kind=='salida' and prior['stage']=='revision':
    ctx=movement_context(c,prior)
    state.update(stage=ctx['stage'],validated=1,expiry_date=ctx['expiry_date'])
   c.execute('UPDATE vessels SET '+','.join(k+'=?' for k in state)+' WHERE id=?',tuple(state.values())+(id,))
  else:
   c.execute('UPDATE history SET event_date=?,description=? WHERE id=?',
     (new_date.isoformat() if new_date else '',description,history_id))
   # If an imported ingreso was the only base, synchronize its visible expiry when
   # the documented expiry was already tied to the previous ingreso date.
   if r['kind']=='ingreso' and new_date and requiredate(r['event_date']) and requiredate(r['expiry_date']):
    old_span=(requiredate(r['expiry_date'])-requiredate(r['event_date'])).days
    if 0<=old_span<=366 and v['stage'] in ('ingreso','revision') and v['expiry_date']==r['expiry_date']:
     new_expiry=(new_date+timedelta(days=old_span)).isoformat()
     c.execute('UPDATE history SET expiry_date=? WHERE id=?',(new_expiry,history_id))
     c.execute('UPDATE vessels SET start_date=?,expiry_date=? WHERE id=?',(new_date.isoformat(),new_expiry,id))
  if linked_return is not None:
   # El retorno anterior ya había incorporado los días calculados desde la
   # salida equivocada. Aplicar solamente la diferencia (una sola vez).
   diff=new_days-old_days
   updated_expiry=(recorded_old+timedelta(days=diff)).isoformat()
   c.execute('UPDATE history SET expiry_date=? WHERE id=?',(updated_expiry,linked_return['id']))
   c.execute('UPDATE vessels SET expiry_date=? WHERE id=?',(updated_expiry,id))
   changes['retorno_dependiente']={'antes':recorded_old.isoformat(),'despues':updated_expiry}
  c.execute('INSERT INTO movement_edit_audit(vessel_id,history_id,before_json,changes_json,backup_name) VALUES(?,?,?,?,?)',
   (id,history_id,json.dumps(dict(r),ensure_ascii=False),json.dumps(changes,ensure_ascii=False),backup_name))
  effective=temporary_exit_summary(c,id)
 return jsonify(ok=True,message='Fecha efectiva corregida. El contador temporal ya utiliza la fecha guardada.',backup=backup_name,
                current_departure=effective['current_departure'],
                return_deadline=effective['return_deadline'],
                note='El vencimiento del retorno posterior también se recalculó.' if linked_return else ('Revisa los movimientos posteriores y su vencimiento.' if later_manual else ''))

@app.post('/api/import/preview')
def import_preview():
 from import_service import run_upload
 f=request.files.get('file')
 if not f or not f.filename.lower().endswith('.xlsx'):return jsonify(error='Adjunta un Excel .xlsx'),400
 try:
  blob=f.read()
  # Vista previa fiel: simulación sobre copia en memoria; no toca la base real.
  with conn() as source, sqlite3.connect(':memory:') as scratch:
   source.backup(scratch)
   stats=run_upload(scratch,blob,True)
  return jsonify({'preview':True,'stats':stats,'filename':f.filename,'note':'No se han modificado registros. Ninguna fecha importada activa alarmas.'})
 except Exception as e:return jsonify(error=str(e)[:250]),400

@app.post('/api/import/commit')
def import_commit():
 from import_service import run_upload
 f=request.files.get('file')
 if not f or not f.filename.lower().endswith('.xlsx'):return jsonify(error='Adjunta un Excel .xlsx'),400
 if request.form.get('confirm')!='IMPORTAR':return jsonify(error='Debe confirmar la importación'),400
 blob=f.read()
 try:
  from datetime import datetime as _dt
  with lock:
   target=DATA_DIR/'backups'/('previo_importacion_'+_dt.now().strftime('%Y%m%d_%H%M%S%f')+'.sqlite3')
   target.parent.mkdir(exist_ok=True)
   with conn() as source, sqlite3.connect(target) as dest:source.backup(dest)
   with conn() as c:stats=run_upload(c,blob,True)
  return jsonify({'ok':True,'stats':stats,'backup':target.name})
 except Exception as e:return jsonify(error='Error de importación: '+str(e)[:200]),400

@app.get('/api/backup/full')
def backup_full():
 """Respaldo portable: SQLite + documentos asociados + manifiesto SHA-256.
 No incluye credenciales de correo, archivos provisionales ni contraseñas.
 """
 from tempfile import TemporaryDirectory
 import zipfile
 stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
 with lock, TemporaryDirectory() as tmp:
  dbcopy=Path(tmp)/'embarcaciones.sqlite3'
  with conn() as source, sqlite3.connect(dbcopy) as target:source.backup(target)
  manifest={'format':'servamar-full-backup-v1','created_at':datetime.now().isoformat(timespec='seconds'),
            'files':[],'missing_documents':[]}
  memory=io.BytesIO()
  with zipfile.ZipFile(memory,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as bundle:
   def add_file(path,arcname):
    blob=path.read_bytes()
    bundle.writestr(arcname,blob)
    manifest['files'].append({'path':arcname,'sha256':hashlib.sha256(blob).hexdigest(),'bytes':len(blob)})
   add_file(dbcopy,'embarcaciones.sqlite3')
   with sqlite3.connect(dbcopy) as snapshot:
    document_rows=snapshot.execute('SELECT storage_name FROM permit_documents ORDER BY id').fetchall()
   seen=set()
   for (storage_name,) in document_rows:
    if not re.fullmatch(r'[0-9a-f]{32}\.(?:pdf|jpg|jpeg|png|webp)',storage_name or ''):
     manifest['missing_documents'].append(storage_name);continue
    if storage_name in seen:continue
    seen.add(storage_name)
    path=DOC_DIR/storage_name
    if path.is_file():add_file(path,'private_permits/'+storage_name)
    else:manifest['missing_documents'].append(storage_name)
   bundle.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
  content=memory.getvalue()
 return send_file(io.BytesIO(content),as_attachment=True,
                  download_name='servamar_respaldo_completo_'+stamp+'.zip',mimetype='application/zip')

@app.get('/api/backup/download')
def backup_download():
 """Descarga una instantánea consistente de SQLite, sin modificar el original."""
 from tempfile import TemporaryDirectory
 with lock, TemporaryDirectory() as tmp:
  name='servamar_respaldo_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.sqlite3'
  target=Path(tmp)/name
  with conn() as source, sqlite3.connect(target) as dest:source.backup(dest)
  content=target.read_bytes()
 return send_file(io.BytesIO(content),as_attachment=True,download_name=name,mimetype='application/octet-stream')

def departure_reminder_rows(c, today=None, horizon=30):
 """Alertas administrativas de retorno, sin cambiar vencimiento ni enviar a clientes.
 Se usan fechas confirmadas de salidas abiertas; los cierres ya procesados se excluyen.
 """
 today=today or date.today()
 result=[]
 vessels=c.execute("SELECT * FROM vessels WHERE validated=1 AND stage IN ('ingreso','ampliacion')").fetchall()
 for vessel in vessels:
  info=temporary_exit_summary(c,vessel['id'],today)
  if not info['currently_away'] or info['must_close'] or info['historical_departure']:continue
  deadline=requiredate(info['return_deadline'])
  for days in (30,15,7,1):
   notify=deadline-timedelta(days=days)
   if today<=notify<=today+timedelta(days=horizon):
    result.append({'vessel_id':vessel['id'],'name':vessel['name'],
      'declaration':vessel['declaration'],'expiry_date':deadline.isoformat(),
      'notify_on':notify.isoformat(),'days_before':days,'category':'retorno_temporal',
      'admin_ready':bool(os.getenv('ADMIN_EMAIL') and os.getenv('SMTP_HOST') and os.getenv('SMTP_FROM')),
      'client_ready':False})
 return result

@app.get('/api/review/queue')
def review_queue():
 """Bandeja informativa. No confirma permisos ni altera la base."""
 try:limit=min(max(int(request.args.get('limit',100)),1),500)
 except ValueError:return jsonify(error='Límite inválido'),400
 dates=current_deadlines(); by_id={r['id']:r for r in dates}
 with conn() as c:
  vessel_rows=c.execute('SELECT * FROM vessels ORDER BY id').fetchall()
  incomplete={r['vessel_id'] for r in c.execute("SELECT DISTINCT vessel_id FROM history WHERE kind IN ('ampliacion_archivo','deposito_archivo','deposito_solicitud_archivo')").fetchall()}
  issues=[]
  for v in vessel_rows:
   if v['validated']:continue
   current=by_id.get(v['id']);why=[]
   if not current:why.append('Sin vencimiento legible')
   else:why.append('Vencimiento histórico no confirmado')
   if v['id'] in incomplete:why.append('Posible ampliación o depósito por verificar')
   if not requiredate(v['start_date']):why.append('Fecha de ingreso no validada')
   issues.append({'id':v['id'],'name':v['name'],'declaration':v['declaration'],
      'expiry_date':current['expiry_date'] if current else None,
      'stage':current['stage'] if current else 'sin determinar','reasons':why})
 issues.sort(key=lambda x:(x['expiry_date'] is None,x['expiry_date'] or '9999-12-31',x['name']))
 return jsonify({'total':len(issues),'items':issues[:limit], 'truncated':len(issues)>limit,
                 'note':'Solo revisión manual: no se activan permisos ni alarmas.'})

def vessel_name_key(name):
 """Normalización conservadora: coincidencias sugeridas, nunca fusionadas."""
 import unicodedata
 raw=unicodedata.normalize('NFKD',str(name or '').upper())
 raw=''.join(ch for ch in raw if not unicodedata.combining(ch))
 return re.sub(r'[^A-Z0-9]','',raw)

@app.get('/api/review/related')
def related_vessels():
 with conn() as c:
  vessels=c.execute('SELECT id,name,declaration,captain FROM vessels ORDER BY id').fetchall()
 groups={}
 for v in vessels:
  key=vessel_name_key(v['name'])
  if len(key)>=4:groups.setdefault(key,[]).append(dict(v))
 related=[{'name':items[0]['name'],'count':len(items),'vessels':items[:20]} for items in groups.values()
          if len(items)>1 and len({x['declaration'].strip().upper() for x in items})>1]
 related.sort(key=lambda x:(-x['count'],x['name']))
 return jsonify({'total_groups':len(related),'items':related[:100], 'truncated':len(related)>100,
   'note':'Posibles expedientes relacionados por nombre; no se fusionan ni eliminan datos.'})

@app.get('/api/alerts/upcoming')
def alerts_upcoming():
 """Listado administrativo de alertas futuras; jamás envía mensajes."""
 today=date.today();last=today+timedelta(days=30);items=[]
 with conn() as c:
  rows=c.execute("SELECT v.*,a.days_before FROM vessels v JOIN alert_settings a ON a.vessel_id=v.id AND a.enabled=1 WHERE v.validated=1 AND v.stage IN ('ingreso','ampliacion','deposito') AND v.expiry_date IS NOT NULL AND v.expiry_date!=''").fetchall()
  for v in rows:
   expiry=requiredate(v['expiry_date'])
   if not expiry or historical_documented_closure(c,v['id']) or temporary_exit_summary(c,v['id'])['currently_away']:continue
   scheduled=due(expiry,v['days_before'])
   if not today<=scheduled<=last:continue
   items.append({'vessel_id':v['id'],'name':v['name'],'declaration':v['declaration'],'stage':v['stage'],'expiry_date':v['expiry_date'],'notify_on':scheduled.isoformat(),'days_before':v['days_before'],'admin_ready':bool(os.getenv('ADMIN_EMAIL') and os.getenv('SMTP_HOST') and os.getenv('SMTP_FROM')),'client_ready':bool(v['email'] and v['client_opt_in'] and v['client_send_approved'] and os.getenv('ENABLE_CLIENT_EMAIL')=='YES')})
  items.extend(departure_reminder_rows(c,today,30))
 return jsonify({'count':len(items),'items':sorted(items,key=lambda x:(x['notify_on'],x['name']))[:1000], 'truncated':len(items)>1000,'sending_enabled':os.getenv('CONFIRM_EMAIL_SEND')=='YES'})

@app.get('/api/alerts/config')
def alerts_config():
 return jsonify({'smtp_ready':all(os.getenv(k) for k in ('SMTP_HOST','SMTP_FROM','SMTP_USER','SMTP_PASSWORD')),'admin_recipient':bool(os.getenv('ADMIN_EMAIL')),'client_enabled':os.getenv('ENABLE_CLIENT_EMAIL')=='YES','send_confirmed':os.getenv('CONFIRM_EMAIL_SEND')=='YES', 'android_push':'Pendiente del despliegue seguro en nube (última etapa)'})

def current_deadlines():
 """Current confirmed dates + historical candidate dates (never authorized implicitly).

 Historical rows may contain requests, so candidates are display-only and never
 feed the notification engine. Vessels with explicitly recorded exits/closures
 are excluded from confirmed alerts by their stage.
 """
 today=date.today();items=[]
 with conn() as c:
  vessels=c.execute('SELECT * FROM vessels').fetchall()
  temporal_rows=c.execute("SELECT id,vessel_id,kind,event_date,description FROM history WHERE kind IN ('salida','retorno','salida_archivo','retorno_archivo') ORDER BY event_date,id").fetchall()
  hist=c.execute("""SELECT vessel_id,kind,event_date,expiry_date FROM history
    WHERE kind IN ('ingreso','ampliacion_archivo','deposito_archivo')
    AND expiry_date IS NOT NULL AND expiry_date != ''""").fetchall()
 temporal_by_vessel={}
 for r in temporal_rows:temporal_by_vessel.setdefault(r['vessel_id'],[]).append(r)
 events={}
 for h in hist:
  exp=requiredate(h['expiry_date'])
  if exp:events.setdefault(h['vessel_id'],[]).append((exp,h['kind'],h['event_date']))
 for v in vessels:
  verified=bool(v['validated']) and v['stage'] in ('ingreso','ampliacion','deposito') and requiredate(v['expiry_date']) is not None
  with conn() as closure_conn:
   historical_closure=historical_documented_closure(closure_conn,v['id'])
  if historical_closure:
   continue  # Cierre documentado prevalece sobre el vencimiento original
  if verified:
   expiry=requiredate(v['expiry_date']);stage=v['stage'];quality='confirmado';candidate_count=0
  elif v['validated'] and v['stage']!='revision':
   # A confirmed exit or closure must never reappear as an active permit.
   continue
  else:
   candidates=events.get(v['id'],[])
   if not candidates:continue
   # Display only: farthest documented expiration across historical phases.
   # Because identity and authorization may be ambiguous, this is NOT an
   # operational current expiration and cannot activate reminders.
   expiry,kind,_=max(candidates,key=lambda e:(e[0], {'ingreso':0,'ampliacion_archivo':1,'deposito_archivo':2}.get(e[1],0)))
   stage={'ingreso':'ingreso','ampliacion_archivo':'ampliacion','deposito_archivo':'deposito'}[kind]
   quality='referencia histórica aceptada' if v['validated'] else 'por verificar';candidate_count=len(candidates)
  remaining=(expiry-today).days
  exit_state=temporary_exit_summary(None,v['id'],today,temporal_by_vessel.get(v['id'],[]))
  away=exit_state['currently_away']
  exceeded=bool(away and exit_state['must_close'])
  # La etiqueta de estado es operativa. En salidas históricas sin retorno
  # no inventamos una resolución administrativa: la advertencia permanece.
  if exceeded:
   status=('Permiso cerrado — 90 días fuera cumplidos (cierre documental por confirmar)'
           if exit_state['historical_departure'] else 'Permiso cerrado — 90 días fuera cumplidos')
  elif away:status='Salida temporal'
  else:status=('Vencido' if remaining<0 else ('Vence hoy' if remaining==0 else 'Vigente'))
  # V43: el plazo operativo de una salida temporal es el límite de 90 días
  # fuera; NO el vencimiento antiguo del ingreso. No cambiar el plazo original
  # almacenado en el expediente ni añadir días sin retorno documentado.
  operational_date=exit_state['return_deadline'] if away else expiry.isoformat()
  operational_remaining=(exit_state['return_days_left'] if away else remaining)
  items.append({**serialize(v),'stage':'cierre' if exceeded else 'salida' if away else stage,
                'permit_stage':stage,'expiry_date':expiry.isoformat(),
                'remaining_days':remaining,'status':status,'temporarily_away':away,
                'operational_date':operational_date,
                'operational_remaining_days':operational_remaining,
                'closure_due_to_90_days':exceeded,
                'date_quality':quality,'candidate_count':candidate_count,
                'return_deadline':exit_state['return_deadline'],
                'return_days_left':exit_state['return_days_left'],
                'historical_departure':exit_state['historical_departure'],
                'days_out':exit_state['current_days_away']})
 return items

@app.get('/api/expirations')
def expirations():
 mode=request.args.get('mode','upcoming')
 if mode not in ('upcoming','overdue','review','departures'):return jsonify(error='Filtro no válido'),400
 items=current_deadlines()
 if DEMO_MODE and CLOUD_MODE:
  from demo_vessels import demo_operational_rows
  items.extend(demo_operational_rows())
 if mode=='upcoming':items=[x for x in items if not x.get('closure_due_to_90_days') and 0<=x['operational_remaining_days']<=30]
 elif mode=='overdue':items=[x for x in items if not x.get('closure_due_to_90_days') and x['operational_remaining_days']<0]
 elif mode=='departures':items=[x for x in items if x['temporarily_away']]
 else:items=[x for x in items if x['date_quality']=='por verificar']
 items.sort(key=lambda x:(x['operational_remaining_days'] if mode!='overdue' else -x['operational_remaining_days'],x['name']))
 limit=200
 return jsonify({'items':items[:limit],'total':len(items),'truncated':len(items)>limit,'mode':mode})

@app.get('/api/expirations.csv')
def expirations_csv():
 from flask import Response
 mode=request.args.get('mode','upcoming')
 if mode not in ('upcoming','overdue','review','departures'):return jsonify(error='Filtro no válido'),400
 records=current_deadlines()
 records=[v for v in records if (not v.get('closure_due_to_90_days') and 0<=v['operational_remaining_days']<=30 if mode=='upcoming' else not v.get('closure_due_to_90_days') and v['operational_remaining_days']<0 if mode=='overdue' else v['temporarily_away'] if mode=='departures' else v['date_quality']=='por verificar')]
 f=io.StringIO();w=csv.writer(f)
 w.writerow(['Embarcación','Declaración','Capitán','Etapa','Fecha de plazo operativo','Estado','Días hasta plazo operativo','Validez documental','Correo cliente'])
 for v in records:
  w.writerow([v['name'],v['declaration'],v['captain'],v['stage'],requiredate(v['operational_date']).strftime('%d/%m/%Y'),v['status'],v['operational_remaining_days'],v['date_quality'],v['email']])
 return Response('\ufeff'+f.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=vencimientos_servamar.csv'})


# V26: consultas de discrepancias, exportaciones y correo manual explícitamente solicitado.
def discrepancies_report():
 """No sobrescribe fechas ni confunde diferencias históricas con error documental."""
 issues=[];valid=0;malformed=0
 with conn() as c:
  rows=c.execute("""SELECT h.id,h.event_date,h.expiry_date,v.id AS vessel_id,v.declaration,v.name
   FROM history h JOIN vessels v ON v.id=h.vessel_id WHERE h.kind='ingreso'""").fetchall()
  totals=c.execute('SELECT COUNT(*) AS n,SUM(validated) AS verified FROM vessels').fetchone()
  for x in rows:
   start=requiredate(x['event_date']);end=requiredate(x['expiry_date'])
   if not start or not end:
    malformed+=1;continue
   valid+=1;delta=(end-start).days
   if delta!=90:
    issues.append({'vessel_id':x['vessel_id'],'declaration':x['declaration'],'name':x['name'],
      'start_date':start.isoformat(),'expiry_date':end.isoformat(),'difference_days':delta-90,
      'actual_days':delta,'expected_date':(start+timedelta(days=90)).isoformat(),
      'reason':'Diferencia respecto al cálculo de 90 días; puede tener justificación documental'})
 return {'summary':{'total_fichas':totals['n'],'validated_in_system':totals['verified'] or 0,
                   'initial_dates_compared':valid,'initial_date_discrepancies':len(issues),
                   'entries_without_two_valid_dates':malformed},'issues':issues,
         'note':'Una diferencia no demuestra error en el permiso. Las fechas originales no se modificaron. El indicador validated corresponde a la confirmación dentro de la app, no a una revisión externa.'}

@app.get('/api/review/date-discrepancies')
def date_discrepancies():return jsonify(discrepancies_report())

@app.post('/api/vessels/<int:id>/confirm-current-deadline')
def confirm_current_deadline(id):
 """Operator confirmation of the current deadline; no document upload required.
 Only the server-derived candidate can be confirmed, never arbitrary client dates.
 """
 data=request.get_json(silent=True) or {}
 if data.get('confirmation')!='CONFIRMAR':
  return jsonify(error='Confirma expresamente el vencimiento mostrado.'),400
 with lock,conn() as c:
  v=c.execute('SELECT * FROM vessels WHERE id=?',(id,)).fetchone()
  if not v:return jsonify(error='Expediente no encontrado'),404
  if v['stage']=='cierre':return jsonify(error='No es posible reactivar un expediente cerrado.'),400
  if v['validated']:return jsonify(ok=True,message='La fecha ya estaba confirmada.')
  ctx=movement_context(c,v)
  if ctx['stage'] not in ('ingreso','ampliacion','deposito') or not requiredate(ctx['expiry_date']):
   return jsonify(error='No existe vencimiento histórico válido que confirmar.'),400
  if data.get('expiry_date')!=ctx['expiry_date']:
   return jsonify(error='La fecha cambió; vuelve a abrir la ficha y revisa el vencimiento.'),409
  c.execute('UPDATE vessels SET validated=1,stage=?,expiry_date=? WHERE id=?',
            (ctx['stage'],ctx['expiry_date'],id))
  c.execute('INSERT INTO edit_audit(vessel_id,changes) VALUES(?,?)',
   (id,json.dumps({'validacion_operador':{'antes':'sin confirmar','despues':ctx['stage']+' '+ctx['expiry_date']}},ensure_ascii=False)))
 return jsonify(ok=True,message='Fecha confirmada por el operador. El envío a clientes sigue sujeto a consentimiento y activación separada.')

# V51: editable mail template stored separately from database and SMTP credentials.
MAIL_TEMPLATE_FILE=DATA_DIR/'plantilla_correo.json'
MAIL_TEMPLATE_DEFAULT={
 'subject':'A friendly reminder / Recordatorio de permiso – {embarcacion}',
 'body':('ENGLISH\nHello, {nombre}:\n\nI hope you are doing very well.\n\n'
         'I am writing to remind you that the permit for your vessel {embarcacion} expires on {vencimiento}, '
         'which is in {dias} days.\n\n'
         'Please reply to this email as soon as possible so I can confirm the details with you '
         'and provide the information needed to arrange any eligible permit extension before the deadline. '
         'Once the permit expires, extension options may no longer be available.\n\n'
         'I will be happy to help and answer any questions you may have.\n\n'
         'Have a wonderful day!\n\nSincerely,\nRaúl Morales\nSERVAMAR\n\n'
         '------------------------------------------\n'
         'ESPAÑOL\nHola, {nombre}:\n\nEspero que te encuentres muy bien.\n\n'
         'Te escribo para recordarte que el permiso de tu embarcación {embarcacion} vencerá el '
         '{vencimiento}, es decir, dentro de {dias} días.\n\n'
         'Después de esa fecha podría no ser posible ampliar tu permiso. Por favor, responde a este '
         'correo lo antes posible para confirmar los detalles y darte toda la información necesaria '
         'sobre las opciones de ampliación que correspondan, antes de su vencimiento.\n\n'
         'Estaré pendiente para ayudarte y resolver cualquier duda que tengas.\n\n'
         '¡Que tengas un excelente día!\n\nAtentamente,\nRaúl Morales\nSERVAMAR')
}
MAIL_FIELDS=('nombre','embarcacion','permiso','vencimiento','dias','etapa_en','etapa_es')

def mail_first_name(captain):
 # Nombre de pila del capitán/titular; el expediente no dispone de campo independiente.
 import re
 parts=str(captain or '').strip().split()
 while parts and parts[0].strip('.').lower() in ('sr','sra','srta','dr','dra','mr','mrs','ms','capt','capitan','capitán'):
  parts.pop(0)
 if not parts:
  return 'estimado cliente'
 first=re.sub(r'[^\wÀ-ÿ\'-]', '',parts[0],flags=re.UNICODE)
 return first.title() if first else 'estimado cliente'

def mail_template():
 if not MAIL_TEMPLATE_FILE.is_file():return dict(MAIL_TEMPLATE_DEFAULT)
 try:
  data=json.loads(MAIL_TEMPLATE_FILE.read_text(encoding='utf-8'))
  if isinstance(data,dict) and all(isinstance(data.get(k),str) for k in ('subject','body')):
   return {'subject':data['subject'],'body':data['body']}
 except (ValueError,OSError):pass
 return dict(MAIL_TEMPLATE_DEFAULT)

def check_mail_template(data):
 if not isinstance(data,dict):raise ValueError('Formato de plantilla inválido')
 subject=str(data.get('subject','')).strip();body=str(data.get('body','')).strip()
 if not (1<=len(subject)<=250 and 1<=len(body)<=18000):
  raise ValueError('Asunto (1–250 caracteres) y mensaje (1–18000 caracteres) obligatorios')
 if any(x in subject for x in '\r\n') or any(ord(x)<32 and x not in '\n\t' for x in body):
  raise ValueError('No se admiten caracteres de control')
 import string
 for value in (subject,body):
  for _,field,format_spec,conversion in string.Formatter().parse(value):
   if field is not None and (field not in MAIL_FIELDS or conversion or format_spec):
    raise ValueError('Variable de plantilla no admitida: '+str(field))
  # Las llaves mal cerradas producen ValueError en Formatter.parse.
 if '{vencimiento}' not in body or '{embarcacion}' not in body:
  raise ValueError('El texto debe incluir {embarcacion} y {vencimiento}')
 return {'subject':subject,'body':body}

def render_mail_text(name,declaration,expiry,stage,template=None,captain=None):
 template=check_mail_template(template or mail_template())
 en={'ingreso':'Initial permit','ampliacion':'Extended permit','deposito':'Customs warehouse deposit'}.get(stage,'Vessel permit')
 es={'ingreso':'Permiso inicial','ampliacion':'Permiso ampliado','deposito':'Depósito aduanero'}.get(stage,'Permiso de embarcación')
 fields={'nombre':mail_first_name(captain),'embarcacion':str(name or ''),'permiso':str(declaration or ''),'vencimiento':expiry.strftime('%d/%m/%Y'),
         'dias':str((expiry-date.today()).days),'etapa_en':en,'etapa_es':es}
 return template['subject'].format(**fields),template['body'].format(**fields)

def styled_mail_html(body):
 from html import escape
 content=escape(body).replace('\n','<br>')
 return ('<!doctype html><html lang="es"><meta charset="utf-8">'
         '<body style="margin:0;background:#f2f6f8;font:15px/1.6 Arial,sans-serif;color:#1e3441;padding:24px 8px">'
         '<div style="max-width:660px;margin:auto;background:white;border:1px solid #dae4e8">'
         '<header style="background:#0d5870;color:#fff;padding:22px 28px;font-size:26px;font-weight:bold">SERVAMAR</header>'
         '<main style="padding:25px 28px;overflow-wrap:anywhere">'+content+'</main>'
         '<footer style="background:#edf3f6;padding:12px 28px;color:#60747e;font-size:12px">'
         'Vessel Permit Management · Control de embarcaciones</footer></div></body></html>')

@app.get('/api/mail-template')
def get_mail_template():
 return jsonify(template=mail_template(),fields=list(MAIL_FIELDS),custom=MAIL_TEMPLATE_FILE.exists())

@app.post('/api/mail-template')
def save_mail_template():
 try:payload=check_mail_template(request.get_json(silent=True) or {})
 except ValueError as exc:return jsonify(error=str(exc)),400
 # Atomic replacement; no edits to vessel records or email activation.
 temporary=MAIL_TEMPLATE_FILE.with_suffix('.tmp')
 temporary.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
 temporary.replace(MAIL_TEMPLATE_FILE)
 return jsonify(ok=True,message='Plantilla general guardada; se usará en los próximos correos.')

@app.post('/api/mail-template/reset')
def reset_mail_template():
 MAIL_TEMPLATE_FILE.unlink(missing_ok=True)
 return jsonify(ok=True,template=mail_template())

@app.get('/api/vessels/<int:id>/manual-email-preview')
def manual_email_preview(id):
 with conn() as c:
  v=c.execute('SELECT * FROM vessels WHERE id=?',(id,)).fetchone()
  if not v:return jsonify(error='Expediente no encontrado'),404
  deadline=next((x for x in current_deadlines() if x['id']==id),None)
  expiry=requiredate(deadline['expiry_date']) if deadline else None
  if not expiry:return jsonify(error='No hay vencimiento calculable para este expediente'),400
  allowed=(bool(v['client_opt_in']) and valid_mail_address(v['email']))
  if v['stage']=='cierre':allowed=False
  if temporary_exit_summary(c,id)['currently_away']:allowed=False
  return jsonify({'declaration':v['declaration'],'vessel':v['name'],'to':v['email'],
    'expiry_date':expiry.isoformat(),'date_quality':deadline['date_quality'],
    'subject':render_mail_text(v['name'],v['declaration'],expiry,deadline['stage'],captain=v['captain'])[0],
    'body':render_mail_text(v['name'],v['declaration'],expiry,deadline['stage'],captain=v['captain'])[1],
    'html':styled_mail_html(render_mail_text(v['name'],v['declaration'],expiry,deadline['stage'],captain=v['captain'])[1]),'eligible':allowed,
    'reasons':([] if allowed else ['Comprueba correo válido y consentimiento del cliente; el permiso no debe estar cerrado ni en salida temporal.'])})

@app.post('/api/vessels/<int:id>/send-manual-email')
def send_manual_email(id):
 """Direct manual client delivery; never activates scheduled client mail."""
 data=request.get_json(silent=True) or {}
 if data.get('confirmation')!='ENVIAR' or data.get('reviewed_email') is not True or data.get('reviewed_date') is not True:
  return jsonify(error='Debes confirmar ENVIAR y revisar expresamente destinatario y vencimiento'),400
 if os.getenv('CONFIRM_EMAIL_SEND')!='YES' or not mail_eligibility()['smtp_ready']:
  return jsonify(error='SMTP no habilitado: configura Gmail y CONFIRM_EMAIL_SEND=YES'),400
 with lock,conn() as c:
  v=c.execute('SELECT * FROM vessels WHERE id=?',(id,)).fetchone()
  if not v:return jsonify(error='Expediente no encontrado'),404
  if not v['client_opt_in'] or not valid_mail_address(v['email']):
   return jsonify(error='Cliente sin correo válido o consentimiento registrado'),400
  if v['stage']=='cierre' or temporary_exit_summary(c,id)['currently_away']:
   return jsonify(error='No se puede enviar desde expediente cerrado o con salida temporal activa'),400
  deadline=next((x for x in current_deadlines() if x['id']==id),None)
  expiry=requiredate(deadline['expiry_date']) if deadline else None
  if not expiry:return jsonify(error='Vencimiento no disponible'),400
  if deadline['date_quality']!='confirmado' and data.get('historical_date_ack') is not True:
   return jsonify(error='Esta fecha procede del historial: confirma expresamente la fecha para este envío individual'),400
  recent=c.execute("SELECT sent_at FROM alert_log WHERE vessel_id=? AND destination='client-manual' AND status='sent' ORDER BY id DESC LIMIT 1",(id,)).fetchone()
  if recent:
   try:
    if (datetime.utcnow()-datetime.strptime(recent['sent_at'],'%Y-%m-%d %H:%M:%S')).total_seconds()<600:
     return jsonify(error='Ya se envió un correo manual en los últimos 10 minutos; evita duplicados'),429
   except ValueError:pass
  # El asunto y cuerpo se reciben SOLO para este envío y no modifican la plantilla general.
  subject=str(data.get('subject','')).strip();content=str(data.get('body','')).strip()
  if not subject or len(subject)>250 or not content or len(content)>18000 or '\r' in subject or '\n' in subject:
   return jsonify(error='Revisa el asunto y el contenido antes de enviar.'),400
  if any(ord(ch)<32 and ch not in '\n\t' for ch in content):
   return jsonify(error='El texto contiene caracteres de control.'),400
  if data.get('reviewed_content') is not True:return jsonify(error='Confirma que revisaste el mensaje editado'),400
  try:send_email(v['email'],subject,content,styled_mail_html(content))
  except Exception as e:
   # No incluir credenciales ni posibles detalles privados de SMTP en la respuesta.
   return jsonify(error='Gmail no pudo enviar el mensaje. Comprueba la configuración y el registro de la aplicación.',error_type=type(e).__name__),502
  # Identificador negativo único de envío para permitir envíos manuales posteriores.
  nonce=-(int(datetime.now().timestamp()*1000000)%2000000000+1)
  c.execute('INSERT INTO alert_log(vessel_id,expiry_date,days_before,destination,status,detail) VALUES(?,?,?,?,?,?)',
            (id,expiry.isoformat(),nonce,'client-manual','sent',v['email']))
 return jsonify(ok=True,recipient=v['email'],expiry_date=expiry.isoformat(),message='Correo manual enviado y registrado')

def export_rows(period,field,from_date,to_date):
 if field not in ('ingreso','vencimiento'):raise ValueError('Campo de fecha inválido')
 if period not in ('all','month','year','previous_year','next30','last30','custom'):raise ValueError('Período inválido')
 today=date.today()
 if period=='month':start,end=date(today.year,today.month,1),add_calendar_months(date(today.year,today.month,1),1)-timedelta(days=1)
 elif period=='year':start,end=date(today.year,1,1),date(today.year,12,31)
 elif period=='previous_year':start,end=date(today.year-1,1,1),date(today.year-1,12,31)
 elif period=='next30':start,end=today,today+timedelta(days=30)
 elif period=='last30':start,end=today-timedelta(days=30),today
 elif period=='custom':
  start=requiredate(from_date);end=requiredate(to_date)
  if not start or not end or end<start:raise ValueError('Indica un período válido (inicio y fin)')
 else:start=end=None
 if start and (end-start).days>36525:raise ValueError('Período demasiado amplio')
 deadlines={x['id']:x for x in current_deadlines()}
 with conn() as c:
  allv=c.execute("""SELECT v.*, (SELECT MIN(h.event_date) FROM history h WHERE h.vessel_id=v.id AND h.kind='ingreso' AND h.event_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]') AS first_entry_date FROM vessels v""").fetchall()
 results=[]
 for v in allv:
  dl=deadlines.get(v['id']);ingress=requiredate(v['first_entry_date']) or requiredate(v['start_date'])
  expiry=requiredate(dl['expiry_date']) if dl else requiredate(v['expiry_date'])
  target=ingress if field=='ingreso' else expiry
  if start and (target is None or target<start or target>end):continue
  remaining=(expiry-today).days if expiry else None
  results.append({'declaration':v['declaration'],'name':v['name'],'registration_number':v['registration_number'],'captain':v['captain'],
   'ingress':ingress.strftime('%d/%m/%Y') if ingress else '',
   'expiry':expiry.strftime('%d/%m/%Y') if expiry else '',
   'stage':dl['stage'] if dl else v['stage'],
   'status':dl['status'] if dl else (('Permiso cerrado — 90 días fuera cumplidos' if v['closure_reason']=='salida temporal sin retorno' else 'Permiso cerrado — cierre registrado') if v['stage']=='cierre' else 'Sin fecha vigente'),
   'remaining':remaining if remaining is not None else '',
   'quality':dl['date_quality'] if dl else ('confirmado' if v['validated'] else 'histórico'),
   'email':v['email'] or ''})
 # Para listados de vencimiento, mostrar primero el más próximo y luego vencidos recientes.
 if field=='vencimiento':results.sort(key=lambda r:(0 if isinstance(r['remaining'],int) and r['remaining']>=0 else 1 if isinstance(r['remaining'],int) else 2,abs(r['remaining']) if isinstance(r['remaining'],int) else 0,r['name']))
 else:results.sort(key=lambda r:(r['ingress'][-4:]+r['ingress'][3:5]+r['ingress'][:2] if r['ingress'] else '',r['name']),reverse=True)
 return results,start,end

EXPORT_HEADERS=['Número ST','Embarcación','Número de registro','Capitán / titular','Fecha de ingreso','Vencimiento vigente o referencia','Etapa','Estado','Días restantes','Calidad de fecha','Correo']
def xlsx_bytes(rows):
 """Genera XLSX con XML estándar, sin macros, fórmulas ni dependencias extra."""
 cols=['declaration','name','registration_number','captain','ingress','expiry','stage','status','remaining','quality','email']
 def cell(value,idx,row):
  addr=chr(65+idx)+str(row)
  if isinstance(value,int):return f'<c r="{addr}"><v>{value}</v></c>'
  txt=xml_escape(str(value or ''),{'"':'&quot;'})
  return f'<c r="{addr}" t="inlineStr"><is><t xml:space="preserve">{txt}</t></is></c>'
 sheetrows=['<row r="1">'+''.join(cell(v,i,1) for i,v in enumerate(EXPORT_HEADERS))+'</row>']
 for j,data in enumerate(rows,2):sheetrows.append(f'<row r="{j}">'+''.join(cell(data.get(k,''),i,j) for i,k in enumerate(cols))+'</row>')
 sheet='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetViews><sheetView workbookViewId="0"/></sheetViews><cols>'+''.join(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>' for i,w in enumerate((19,30,22,29,17,24,16,22,17,20,29),1))+'</cols><sheetData>'+''.join(sheetrows)+'</sheetData><autoFilter ref="A1:J'+str(len(rows)+1)+'"/></worksheet>'
 out=io.BytesIO()
 with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
  z.writestr('[Content_Types].xml','<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
  z.writestr('_rels/.rels','<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
  z.writestr('xl/workbook.xml','<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Control de embarcaciones" sheetId="1" r:id="rId1"/></sheets></workbook>')
  z.writestr('xl/_rels/workbook.xml.rels','<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
  z.writestr('xl/worksheets/sheet1.xml',sheet)
 return out.getvalue()

def pdf_bytes(rows,period_label):
 from reportlab.pdfgen import canvas
 from reportlab.lib.pagesizes import landscape,A4
 out=io.BytesIO();page=landscape(A4);p=canvas.Canvas(out,pagesize=page)
 width,height=page;page_no=0;y=0
 def header():
  nonlocal y,page_no
  page_no+=1;p.setFont('Helvetica-Bold',14);p.drawString(32,height-36,'SERVAMAR - Control de embarcaciones')
  p.setFont('Helvetica',9);p.drawString(32,height-52,period_label+' | Fecha de reporte: '+date.today().strftime('%d/%m/%Y')+' | Registros: '+str(len(rows)))
  p.line(32,height-62,width-32,height-62);y=height-80
  p.setFont('Helvetica-Bold',8)
  for x,t in [(32,'ST'),(135,'Embarcación'),(280,'Ingreso'),(350,'Vencimiento'),(430,'Etapa'),(510,'Estado'),(635,'Dias'),(680,'Fecha')]:p.drawString(x,y,t)
  y-=16;p.setFont('Helvetica',8)
 header()
 for r in rows:
  if y<42:p.setFont('Helvetica',8);p.drawRightString(width-30,26,'Página '+str(page_no));p.showPage();header()
  vals=[(32,r['declaration'],17),(135,r['name'],25),(280,r['ingress'],10),(350,r['expiry'],10),(430,r['stage'],12),(510,r['status'],20),(635,str(r['remaining']),7),(680,r['quality'],17)]
  for x,s,maxlen in vals:
   s=str(s or '').replace('–','-').replace('—','-');p.drawString(x,y,s[:maxlen-3]+'...' if len(s)>maxlen else s)
  y-=15
 p.drawRightString(width-30,26,'Página '+str(page_no));p.save();return out.getvalue()

@app.get('/api/version')
def app_version():
 return jsonify(version=VERSION,storage=str(DATA_DIR),gmail_configured=bool(os.getenv('SMTP_HOST') and os.getenv('SMTP_USER')),cloud_enabled=CLOUD_MODE,lan_enabled=LAN_MODE)

@app.get('/api/control/export')
def control_export():
 fmt=request.args.get('format','xlsx').lower()
 if fmt not in ('xlsx','pdf'):return jsonify(error='Formato no válido'),400
 period=request.args.get('period','all');field=request.args.get('field','vencimiento')
 try:rows,start,end=export_rows(period,field,request.args.get('from',''),request.args.get('to',''))
 except ValueError as e:return jsonify(error=str(e)),400
 label={'all':'Todo el historial','month':'Mes actual','year':'Año actual','previous_year':'Año anterior','next30':'Próximos 30 días','last30':'Últimos 30 días','custom':'Período seleccionado'}.get(period)
 if label is None:return jsonify(error='Período inválido'),400
 if start:label+=': '+start.strftime('%d/%m/%Y')+' al '+end.strftime('%d/%m/%Y')
 try:
  output=xlsx_bytes(rows) if fmt=='xlsx' else pdf_bytes(rows,label)
 except ImportError:
  return jsonify(error='Falta instalar ReportLab. Ejecuta: python -m pip install -r requirements.txt'),503
 except Exception:
  app.logger.exception('Error al generar exportación %s',fmt)
  return jsonify(error='No se pudo generar el archivo. Revisa la terminal de SERVAMAR.'),500
 return send_file(io.BytesIO(output),as_attachment=True,download_name='SERVAMAR_Control_'+date.today().strftime('%Y%m%d')+'.'+fmt,
                  mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' if fmt=='xlsx' else 'application/pdf')

@app.get('/api/alerts/preview')
def alerts_preview():
 """Preview only: never sends an email."""
 day=requiredate(request.args.get('date')) or date.today()
 items=[]
 with conn() as c:
  rows=c.execute("SELECT v.*,a.days_before FROM vessels v JOIN alert_settings a ON a.vessel_id=v.id AND a.enabled=1 WHERE v.validated=1 AND v.stage IN ('ingreso','ampliacion','deposito') AND v.expiry_date!=''").fetchall()
  for v in rows:
   exp=requiredate(v['expiry_date'])
   if not exp or temporary_exit_summary(c,v['id'])['currently_away'] or due(exp,v['days_before'])!=day:continue
   items.append({'vessel_id':v['id'],'name':v['name'],'declaration':v['declaration'],'expiry_date':v['expiry_date'],'days_before':v['days_before'],'admin':bool(os.getenv('ADMIN_EMAIL')),'client':bool(v['client_opt_in'] and v['client_send_approved'] and v['email'] and os.getenv('ENABLE_CLIENT_EMAIL')=='YES')})
  for reminder in departure_reminder_rows(c,day,0):
   items.append({'vessel_id':reminder['vessel_id'],'name':reminder['name'],
     'declaration':reminder['declaration'],'expiry_date':reminder['expiry_date'],
     'days_before':reminder['days_before'],'admin':bool(os.getenv('ADMIN_EMAIL')),
     'client':False,'category':'retorno_temporal'})
 return jsonify({'date':day.isoformat(),'count':len(items),'items':items})

@app.get('/api/dashboard')
def dashboard():
 dates=current_deadlines()
 with conn() as c:total=c.execute('SELECT COUNT(*) FROM vessels').fetchone()[0]
 demo_total=0
 if DEMO_MODE and CLOUD_MODE:
  from demo_vessels import demo_operational_rows,dbconnect
  dates.extend(demo_operational_rows())
  with dbconnect() as db:
   demo_total=db.execute('SELECT COUNT(*) FROM servamar_demo_vessels').fetchone()[0]
 return jsonify({'total':total+demo_total,'demo_pg_count':demo_total,
   'review':total-sum(v['date_quality']=='confirmado' for v in dates if not v.get('demo_pg')),
   'active':sum(v['remaining_days']>=0 and v['date_quality']=='confirmado' for v in dates),
   'soon':sum(not v.get('closure_due_to_90_days') and 0<=v['operational_remaining_days']<=30 for v in dates),
   'expired':sum(not v.get('closure_due_to_90_days') and v['operational_remaining_days']<0 for v in dates),
   'deposit':sum(v['stage']=='deposito' for v in dates)})
def send_email(to,subject,body,html_body=None):
 """Send a multipart message when HTML is supplied; text fallback is mandatory."""
 host=os.getenv('SMTP_HOST');sender=os.getenv('SMTP_FROM');user=os.getenv('SMTP_USER');password=os.getenv('SMTP_PASSWORD')
 if not all((host,sender,user,password)):raise RuntimeError('SMTP no configurado')
 msg=EmailMessage();msg['From']=sender;msg['To']=to;msg['Subject']=subject;msg.set_content(body)
 if html_body:msg.add_alternative(html_body,subtype='html')
 port=int(os.getenv('SMTP_PORT','465'))
 if port==465:
  with smtplib.SMTP_SSL(host,port,context=ssl.create_default_context(),timeout=20) as smtp:smtp.login(user,password);smtp.send_message(msg)
 else:
  with smtplib.SMTP(host,port,timeout=20) as smtp:smtp.starttls(context=ssl.create_default_context());smtp.login(user,password);smtp.send_message(msg)
def valid_mail_address(value):
 """Conservative check: no spaces, control chars or multiple addresses."""
 value=str(value or '').strip()
 if len(value)>254 or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", value):
  return False
 return True

def client_email_subject(name):
 return 'Permit Expiration Notice / Aviso de vencimiento – '+str(name or 'Vessel')

def client_message(name, declaration, expiry, stage=None):
 """Plain-text bilingual version. English MUST appear before Spanish."""
 expiry_text=expiry.strftime('%d/%m/%Y')
 diff=(expiry-date.today()).days
 if diff>0:remaining_en=f'{diff} day(s) remaining';remaining_es=f'Faltan {diff} día(s)'
 elif diff==0:remaining_en='Expires today';remaining_es='Vence hoy'
 else:remaining_en=f'Expired {abs(diff)} day(s) ago';remaining_es=f'Vencido hace {abs(diff)} día(s)'
 stage_en={'ingreso':'Initial permit','ampliacion':'Extended permit','deposito':'Customs warehouse deposit'}.get(stage,'Vessel permit')
 stage_es={'ingreso':'Permiso inicial','ampliacion':'Permiso ampliado','deposito':'Depósito aduanero'}.get(stage,'Permiso de embarcación')
 return (f'SERVAMAR | PERMIT EXPIRATION REMINDER\n\n'
         f'ENGLISH\nDear Client,\n\nWarm greetings from SERVAMAR.\n\n'
         f'We would like to inform you that the authorization for the following vessel is approaching or has reached its expiration date:\n\n'
         f'Vessel: {name}\nPermit number: {declaration}\nPermit type: {stage_en}\n'
         f'Expiration date (DD/MM/YYYY): {expiry_text}\n{remaining_en}\n\n'
         'We recommend contacting our office in advance to arrange the appropriate procedures and avoid inconvenience. '
         'If you have already completed the necessary procedures, please let us know so we can update your records.\n\n'
         'Best regards,\nSERVAMAR\n\n'
         '------------------------------------------------------------\n'
         f'ESPAÑOL\nEstimado(a) cliente:\n\nReciba un cordial saludo de SERVAMAR.\n\n'
         'Le informamos que la autorización de la siguiente embarcación está próxima a vencer o ha alcanzado su fecha de vencimiento:\n\n'
         f'Embarcación: {name}\nNúmero de permiso: {declaration}\nTipo de permiso: {stage_es}\n'
         f'Fecha de vencimiento (DD/MM/AAAA): {expiry_text}\n{remaining_es}\n\n'
         'Le recomendamos comunicarse con nuestra oficina con anticipación para coordinar el trámite correspondiente y evitar inconvenientes. '
         'Si ya realizó el trámite, agradeceremos que nos informe para actualizar su expediente.\n\n'
         'Atentamente,\nSERVAMAR')

def client_message_html(name, declaration, expiry, stage=None):
 """Escaped, responsive HTML; one bilingual email, English first."""
 name,decl=html_escape(str(name or '')),html_escape(str(declaration or ''))
 expiry_text=expiry.strftime('%d/%m/%Y')
 diff=(expiry-date.today()).days
 if diff>0:en_status=f'{diff} day(s) until expiration';es_status=f'{diff} día(s) para el vencimiento'
 elif diff==0:en_status='Expires today';es_status='Vence hoy'
 else:en_status=f'Expired {abs(diff)} day(s) ago';es_status=f'Vencido hace {abs(diff)} día(s)'
 en_stage={'ingreso':'Initial permit','ampliacion':'Extended permit','deposito':'Customs warehouse deposit'}.get(stage,'Vessel permit')
 es_stage={'ingreso':'Permiso inicial','ampliacion':'Permiso ampliado','deposito':'Depósito aduanero'}.get(stage,'Permiso de embarcación')
 return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="margin:0;padding:22px 10px;background:#f2f6f8;font:15px/1.55 Arial,Helvetica,sans-serif;color:#1e3441">
<table role="presentation" style="max-width:650px;width:100%;margin:auto;border-collapse:collapse;background:white;border:1px solid #dce5e9"><tr><td style="padding:26px 28px;background:#0d5870;color:white"><div style="font-size:27px;font-weight:700;letter-spacing:1px">SERVAMAR</div><div style="font-size:13px">Vessel Permit Management · Control y seguimiento de embarcaciones</div></td></tr>
<tr><td style="padding:26px 28px"><div style="background:#e9f4f7;border-left:5px solid #17829c;padding:14px 18px;margin-bottom:22px"><div style="font-size:12px;color:#325969;font-weight:700">PERMIT REMINDER / RECORDATORIO</div><div style="font-size:20px;font-weight:700">{en_status}</div><div>{es_status}</div></div>
<h2 style="margin:0 0 12px;font-size:19px;color:#0d5870">English</h2><p>Dear Client,</p><p>Warm greetings from <strong>SERVAMAR</strong>.</p><p>We would like to inform you that your vessel's permit is approaching or has reached its expiration date.</p>
<table role="presentation" style="width:100%;border-collapse:collapse;border:1px solid #dce5e9;margin:14px 0"><tr><td style="padding:9px;background:#f1f6f8">Vessel</td><td style="padding:9px"><strong>{name}</strong></td></tr><tr><td style="padding:9px;background:#f1f6f8">Permit number</td><td style="padding:9px">{decl}</td></tr><tr><td style="padding:9px;background:#f1f6f8">Permit type</td><td style="padding:9px">{en_stage}</td></tr><tr><td style="padding:9px;background:#f1f6f8">Expiration date</td><td style="padding:9px"><strong>{expiry_text}</strong> (DD/MM/YYYY)</td></tr></table>
<p>We recommend contacting our office in advance to arrange the appropriate procedures and avoid any inconvenience related to your permit's expiration.</p><p>If you have already completed the necessary procedures, please let us know so we can update your records.</p><p>Best regards,<br><strong>SERVAMAR</strong></p>
<hr style="border:0;border-top:2px solid #d7e6eb;margin:30px 0"><h2 style="margin:0 0 12px;font-size:19px;color:#0d5870">Español</h2><p>Estimado(a) cliente:</p><p>Reciba un cordial saludo de <strong>SERVAMAR</strong>.</p><p>Le informamos que el permiso de permanencia de su embarcación está próximo a vencer o ha alcanzado su fecha de vencimiento.</p>
<table role="presentation" style="width:100%;border-collapse:collapse;border:1px solid #dce5e9;margin:14px 0"><tr><td style="padding:9px;background:#f1f6f8">Embarcación</td><td style="padding:9px"><strong>{name}</strong></td></tr><tr><td style="padding:9px;background:#f1f6f8">Número ST</td><td style="padding:9px">{decl}</td></tr><tr><td style="padding:9px;background:#f1f6f8">Tipo de permiso</td><td style="padding:9px">{es_stage}</td></tr><tr><td style="padding:9px;background:#f1f6f8">Vencimiento</td><td style="padding:9px"><strong>{expiry_text}</strong> (DD/MM/AAAA)</td></tr></table>
<p>Le recomendamos comunicarse con nuestra oficina con anticipación para coordinar el trámite que corresponda y evitar inconvenientes.</p><p>Si ya realizó el trámite correspondiente, agradeceremos que nos informe para actualizar su expediente.</p><p>Atentamente,<br><strong>SERVAMAR</strong></p></td></tr><tr><td style="padding:14px 28px;background:#edf3f6;color:#60747e;font-size:12px">SERVAMAR · Informative notice / Aviso informativo</td></tr></table></body></html>"""

def client_readiness_report():
 """Audit only: no PII, emails, contacts or database writes."""
 summary={'total':0,'validated_open':0,'missing_confirmed_expiry':0,
  'missing_email':0,'invalid_email':0,'missing_client_consent':0,
  'missing_send_approval':0,'ready':0,'temporary_exit':0}
 with conn() as c:
  rows=c.execute('SELECT * FROM vessels').fetchall()
  summary['total']=len(rows)
  for v in rows:
   if historical_documented_closure(c,v['id']) or not v['validated'] or v['stage'] not in ('ingreso','ampliacion','deposito') or not requiredate(v['expiry_date']):
    summary['missing_confirmed_expiry']+=1;continue
   summary['validated_open']+=1
   if temporary_exit_summary(c,v['id'])['currently_away']:
    summary['temporary_exit']+=1;continue
   if not v['email']:summary['missing_email']+=1;continue
   if not valid_mail_address(v['email']):summary['invalid_email']+=1;continue
   if not v['client_opt_in']:summary['missing_client_consent']+=1;continue
   if not v['client_send_approved']:summary['missing_send_approval']+=1;continue
   summary['ready']+=1
 return {'summary':summary,'email_to_clients_enabled':os.getenv('ENABLE_CLIENT_EMAIL')=='YES',
  'note':'Solo auditoría: no se envía correo, no se modifica la base y no se muestran direcciones.'}

def send_client_template_test():
 """Live SMTP test ONLY to ADMIN_EMAIL with invented demo data."""
 recipient=os.getenv('ADMIN_EMAIL','').strip()
 if not valid_mail_address(recipient):raise ValueError('ADMIN_EMAIL inválido')
 if not mail_eligibility()['smtp_ready']:raise ValueError('SMTP no configurado')
 if os.getenv('CONFIRM_EMAIL_SEND')!='YES':raise ValueError('CONFIRM_EMAIL_SEND debe ser YES')
 fake_expiry=date(2030,1,20)
 subject='[INTERNAL TEST / PRUEBA INTERNA] '+client_email_subject('DEMO VESSEL')
 body=('PRUEBA INTERNA PARA ADMINISTRACION. Datos ficticios.\n\n'
       +client_message('DEMO VESSEL / EMBARCACIÓN DE PRUEBA','ST-DEMO-000',fake_expiry,'ingreso'))
 send_email(recipient,subject,body,client_message_html('DEMO VESSEL / EMBARCACIÓN DE PRUEBA','ST-DEMO-000',fake_expiry,'ingreso'))
 return {'ok':True,'destination':'solo administracion','test_data':'ficticios',
  'note':'No se enviaron correos a clientes.'}

def mail_eligibility():
 return {'smtp_ready':all(os.getenv(k) for k in ('SMTP_HOST','SMTP_FROM','SMTP_USER','SMTP_PASSWORD')),
         'admin_configured':bool(os.getenv('ADMIN_EMAIL','').strip()),
         'sending_confirmed':os.getenv('CONFIRM_EMAIL_SEND')=='YES',
         'clients_enabled':os.getenv('ENABLE_CLIENT_EMAIL')=='YES'}

def planned_alerts_for_day(today=None):
 """Read-only simulation: never transmits email and never logs it."""
 today=today or date.today();items=[]
 with conn() as c:
  rows=c.execute("SELECT v.*,a.days_before FROM vessels v JOIN alert_settings a ON a.vessel_id=v.id AND a.enabled=1 WHERE v.validated=1 AND v.stage IN ('ingreso','ampliacion','deposito') AND v.expiry_date IS NOT NULL AND v.expiry_date!=''").fetchall()
  for v in rows:
   expiry=requiredate(v['expiry_date']);days=v['days_before']
   if not expiry or due(expiry,days)!=today or temporary_exit_summary(c,v['id'],today)['currently_away']:continue
   recipients=[]
   if os.getenv('ADMIN_EMAIL','').strip():recipients.append('administracion')
   if (os.getenv('ENABLE_CLIENT_EMAIL')=='YES' and v['client_opt_in'] and
       v['client_send_approved'] and valid_mail_address(v['email'])):recipients.append('cliente')
   items.append({'vessel_id':v['id'],'declaration':v['declaration'],'vessel':v['name'],
                 'category':'vencimiento','expiry_date':expiry.isoformat(),
                 'days_before':days,'recipients':recipients})
  for r in departure_reminder_rows(c,today,0):
   items.append({'vessel_id':r['vessel_id'],'declaration':r['declaration'],
                 'vessel':r['name'],'category':'retorno_temporal',
                 'expiry_date':r['expiry_date'],'days_before':r['days_before'],
                 'recipients':['administracion'] if os.getenv('ADMIN_EMAIL','').strip() else []})
 if DEMO_MODE and CLOUD_MODE:
  from demo_vessels import demo_reminders_for_day
  items.extend(demo_reminders_for_day(today))
 return {'date':today.isoformat(),'count':len(items),'configuration':mail_eligibility(),'items':items}

def send_admin_test():
 """A manual administrator-only test, never to clients or vessel addresses."""
 recipient=os.getenv('ADMIN_EMAIL','').strip()
 if not recipient or '@' not in recipient:raise ValueError('Configura ADMIN_EMAIL con un correo válido.')
 if not mail_eligibility()['smtp_ready']:raise ValueError('Configura SMTP_HOST, SMTP_USER, SMTP_PASSWORD y SMTP_FROM.')
 if os.getenv('CONFIRM_EMAIL_SEND')!='YES':raise ValueError('Prueba bloqueada: CONFIRM_EMAIL_SEND debe ser YES.')
 subject='SERVAMAR - Prueba de correo administrativo'
 body=('Este mensaje es una prueba manual del servicio de correo SERVAMAR.\n\n'
       'No contiene datos de embarcaciones ni se envió a clientes.\n'
       'Los avisos automáticos requieren una tarea programada y fechas validadas.')
 send_email(recipient,subject,body)
 return {'ok':True,'destination':'administracion','message':'Prueba administrativa enviada; verifica la bandeja de entrada.'}

def run_daily_admin():
 """Explicitly activated administrator-only scheduled job. Never sends to clients."""
 if os.getenv('ENABLE_ADMIN_AUTOMATION')!='YES':
  raise RuntimeError('Revisión automática desactivada: ENABLE_ADMIN_AUTOMATION debe ser YES.')
 if os.getenv('CONFIRM_EMAIL_SEND')!='YES':
  raise RuntimeError('Envíos bloqueados: CONFIRM_EMAIL_SEND debe ser YES.')
 eligibility=mail_eligibility()
 if not eligibility['smtp_ready'] or not eligibility['admin_configured']:
  raise RuntimeError('Configura correctamente SMTP y ADMIN_EMAIL antes de automatizar.')
 from datetime import datetime as _datetime
 from tempfile import TemporaryDirectory
 with lock:
  with conn() as c:
   closed=reconcile_temporary_closures(c)
  # Respaldo consistente local antes del proceso; fallo del respaldo impide enviar.
  backup_dir=DATA_DIR/'backups'; backup_dir.mkdir(exist_ok=True)
  backup=backup_dir/('diario_'+_datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.sqlite3')
  with conn() as source,sqlite3.connect(backup) as dest:source.backup(dest)
  try:
   result=process_alerts(admin_only=True)
  except Exception as e:
   _record_daily_run({'ok':False,'closed':closed,'error_type':type(e).__name__})
   raise
  _record_daily_run({'ok':result['failed']==0,'closed':closed,'sent':result['sent'],'failed':result['failed'],'backup':backup.name})
  return {'ok':result['failed']==0,'closures':closed,'admin_sent':result['sent'],'failed':result['failed'],'backup':backup.name}

def _record_daily_run(summary):
 """Local JSONL execution log, excluding emails and credentials."""
 row={'at':datetime.now().isoformat(timespec='seconds'),**summary}
 with (DATA_DIR/'avisos_ejecuciones.jsonl').open('a',encoding='utf-8') as f:
  f.write(json.dumps(row,ensure_ascii=False)+'\n')

def process_alerts(admin_only=False):
 """Send only confirmed reminders. admin_only is a hard barrier against client delivery."""
 today=date.today();sent=0;failed=0
 with lock,conn() as c:
  rows=c.execute("SELECT v.*,a.days_before FROM vessels v JOIN alert_settings a ON a.vessel_id=v.id AND a.enabled=1 WHERE v.validated=1 AND v.stage IN ('ingreso','ampliacion','deposito') AND v.expiry_date IS NOT NULL AND v.expiry_date != ''").fetchall()
  for v in rows:
   exp=requiredate(v['expiry_date']);days=v['days_before']
   if not exp or historical_documented_closure(c,v['id']) or temporary_exit_summary(c,v['id'])['currently_away'] or due(exp,days)!=today:continue
   recipients=[];admin=os.getenv('ADMIN_EMAIL','').strip()
   if admin:recipients.append(('admin',admin))
   if not admin_only and os.getenv('ENABLE_CLIENT_EMAIL')=='YES' and v['client_opt_in'] and v['client_send_approved'] and valid_mail_address(v['email']):recipients.append(('client',v['email']))
   for destination,to in recipients:
    if c.execute("SELECT 1 FROM alert_log WHERE vessel_id=? AND expiry_date=? AND days_before=? AND destination=? AND status='sent'",(v['id'],v['expiry_date'],days,destination)).fetchone():continue
    subject=client_email_subject(v['name'])
    body=client_message(v['name'],v['declaration'],exp,v['stage'])
    try:send_email(to,subject,body,client_message_html(v['name'],v['declaration'],exp,v['stage']));status='sent';detail=to;sent+=1
    except Exception as e:status='failed';detail=str(e)[:250];failed+=1
    c.execute('INSERT INTO alert_log(vessel_id,expiry_date,days_before,destination,status,detail) VALUES(?,?,?,?,?,?) ON CONFLICT(vessel_id,expiry_date,days_before,destination) DO UPDATE SET status=excluded.status,detail=excluded.detail,sent_at=CURRENT_TIMESTAMP',(v['id'],v['expiry_date'],days,destination,status,detail))
  if os.getenv('ADMIN_EMAIL'):
   for reminder in departure_reminder_rows(c,today,0):
    v_id=reminder['vessel_id']; deadline=reminder['expiry_date']; days=reminder['days_before']
    destination='admin-retorno-temporal'
    if c.execute("SELECT 1 FROM alert_log WHERE vessel_id=? AND expiry_date=? AND days_before=? AND destination=? AND status='sent'",(v_id,deadline,days,destination)).fetchone():continue
    subject='Salida temporal: plazo de retorno – '+reminder['name']
    body=(f"SERVAMAR\n\nLa embarcación {reminder['name']} ({reminder['declaration']}) tiene "
          f"como fecha límite de retorno el {requiredate(deadline).strftime('%d/%m/%Y')}. "
          f"Restan {days} días. Compruebe los documentos y el estado del expediente.\n\n"
          'Aviso interno; no se ha notificado al cliente.')
    try:send_email(os.environ['ADMIN_EMAIL'],subject,body);status='sent';detail=os.environ['ADMIN_EMAIL'];sent+=1
    except Exception as e:status='failed';detail=str(e)[:250];failed+=1
    c.execute('INSERT INTO alert_log(vessel_id,expiry_date,days_before,destination,status,detail) VALUES(?,?,?,?,?,?) ON CONFLICT(vessel_id,expiry_date,days_before,destination) DO UPDATE SET status=excluded.status,detail=excluded.detail,sent_at=CURRENT_TIMESTAMP',(v_id,deadline,days,destination,status,detail))
 return {'sent':sent,'failed':failed}

def accept_historical_records_once():
 """Operator-requested acceptance of imported records for consultation.
 It is NOT evidence that an historical request was authorized; stage=revision
 stays unchanged. No client consent or scheduled-mail approval is granted.
 """
 with lock, conn() as c:
  c.execute('CREATE TABLE IF NOT EXISTS app_migrations (name TEXT PRIMARY KEY, applied_at TEXT DEFAULT CURRENT_TIMESTAMP, detail TEXT)')
  if c.execute("SELECT 1 FROM app_migrations WHERE name='v30_accept_historical' ").fetchone():return
  count=c.execute('SELECT COUNT(*) FROM vessels WHERE validated=0').fetchone()[0]
  if count:
   folder=DATA_DIR/'backups';folder.mkdir(parents=True,exist_ok=True)
   path=folder/('antes_aceptacion_historicos_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.sqlite3')
   with sqlite3.connect(path) as backup:c.backup(backup)
   c.execute('UPDATE vessels SET validated=1 WHERE validated=0')
  c.execute('INSERT INTO app_migrations(name,detail) VALUES (?,?)',('v30_accept_historical',f'{count} fichas históricas aceptadas para consulta por instrucción del operador. Fechas y etapas originales conservadas. Sin consentimiento de clientes.'))

if __name__=='__main__':
 import sys
 init()
 accept_historical_records_once()
 reconcile_historical_temporary_dates_once()
 if '--backup' in sys.argv:
  from datetime import datetime as _dt
  target=DATA_DIR/'backups'/('embarcaciones_'+_dt.now().strftime('%Y%m%d_%H%M%S')+'.sqlite3')
  target.parent.mkdir(exist_ok=True)
  with conn() as source, sqlite3.connect(target) as dest:source.backup(dest)
  print('Respaldo creado:',target)
 elif '--reconcile-closures' in sys.argv:
  with lock,conn() as c:print('Permisos cerrados automáticamente:',reconcile_temporary_closures(c))
 elif '--preview-alerts' in sys.argv:
  with app.test_request_context('/api/alerts/preview'):
   print(json.dumps(alerts_preview().get_json(),ensure_ascii=False,indent=2))
 elif '--simulate-alerts' in sys.argv:
  selected=None
  for arg in sys.argv:
   if arg.startswith('--date='):
    selected=requiredate(arg.partition('=')[2])
    if selected is None:raise SystemExit('Fecha inválida; utiliza --date=AAAA-MM-DD')
  print(json.dumps(planned_alerts_for_day(selected),ensure_ascii=False,indent=2))
 elif '--audit-client-readiness' in sys.argv:
  print(json.dumps(client_readiness_report(),ensure_ascii=False,indent=2))
 elif '--test-client-template' in sys.argv:
  if '--yes-admin-template-test' not in sys.argv:
   raise SystemExit('Confirmación necesaria: --yes-admin-template-test')
  print(json.dumps(send_client_template_test(),ensure_ascii=False,indent=2))
 elif '--test-admin-email' in sys.argv:
  if '--yes-admin-test' not in sys.argv:raise SystemExit('Confirma la prueba manual con --yes-admin-test')
  print(json.dumps(send_admin_test(),ensure_ascii=False,indent=2))
 elif '--windows-notifications' in sys.argv:
  from windows_notificaciones import run_windows_notifications
  print(json.dumps(run_windows_notifications(),ensure_ascii=False,indent=2))
 elif '--windows-preview' in sys.argv:
  from windows_notificaciones import preview_windows_notifications
  print(json.dumps(preview_windows_notifications(),ensure_ascii=False,indent=2))
 elif '--daily-admin' in sys.argv:
  print(json.dumps(run_daily_admin(),ensure_ascii=False,indent=2))
 elif '--send-alerts' in sys.argv:
  if '--yes-client-send' not in sys.argv:raise SystemExit('Bloqueado: para envíos a clientes se requiere --yes-client-send. La tarea automática de Windows solo usa --daily-admin.')
  if os.getenv('CONFIRM_EMAIL_SEND')!='YES':raise SystemExit('Envíos bloqueados: establecer CONFIRM_EMAIL_SEND=YES solamente tras verificar los datos y configurar SMTP.')
  print(process_alerts())
 else:app.run(host='127.0.0.1',port=int(os.getenv('PORT',8766)),debug=False)
else:
 init()
 if DEMO_MODE:
  with conn() as c:
   if not c.execute('SELECT COUNT(*) FROM vessels').fetchone()[0]:
    for delta,decl,name,cap in [(15,'ST-DEMO-001','EMBARCACIÓN DE PRUEBA A','Capitán Ejemplo'),(30,'ST-DEMO-002','EMBARCACIÓN DE PRUEBA B','Persona Ficticia'),(50,'ST-DEMO-003','EMBARCACIÓN DE PRUEBA C','Usuario Demostración')]:
     start=(date.today()-timedelta(days=90-delta)).isoformat()
     end=(date.today()+timedelta(days=delta)).isoformat()
     c.execute("INSERT INTO vessels(declaration,name,captain,stage,start_date,expiry_date,validated,notes) VALUES(?,?,?,?,?,?,?,?)",(decl,name,cap,'ingreso',start,end,1,'DATOS FICTICIOS: PRUEBA GRATUITA'))
   # Solo fechas ficticias: vincular recordatorios sin alterar registros reales.
   for sample in c.execute("SELECT id FROM vessels WHERE declaration LIKE 'ST-DEMO-%'").fetchall():
    c.executemany("INSERT OR IGNORE INTO alert_settings(vessel_id,days_before,enabled) VALUES(?,?,1)",[(sample['id'],30),(sample['id'],15),(sample['id'],1)])
 else:
  accept_historical_records_once()
  reconcile_historical_temporary_dates_once()
