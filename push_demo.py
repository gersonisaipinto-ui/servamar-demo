"""Temporary Web Push demo; never includes vessel data."""
import base64,hashlib,json,os,sqlite3,threading,time
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from urllib.parse import urlsplit
from flask import Blueprint,jsonify,request
bp=Blueprint("servamar_push_demo",__name__)
dbpath=None
pempath=None
lock=threading.RLock()

def init_push(app,data_dir):
 global dbpath,pempath
 dbpath=Path(data_dir)/"webpush_demo.sqlite3"
 pempath=Path(data_dir)/"webpush_demo_vapid.pem"
 with sqlite3.connect(dbpath) as db:
  db.execute("CREATE TABLE IF NOT EXISTS subscriptions(id TEXT PRIMARY KEY, content TEXT NOT NULL)")
  db.execute("CREATE TABLE IF NOT EXISTS daily_delivery(day TEXT PRIMARY KEY, status TEXT NOT NULL, count INTEGER NOT NULL, recipients INTEGER NOT NULL, completed_at TEXT NOT NULL)")
 app.register_blueprint(bp)

def keys():
 from cryptography.hazmat.primitives.asymmetric import ec
 from cryptography.hazmat.primitives import serialization
 with lock:
  if pempath.exists(): key=serialization.load_pem_private_key(pempath.read_bytes(),password=None)
  else:
   key=ec.generate_private_key(ec.SECP256R1())
   raw=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
   with pempath.open("xb") as f:f.write(raw)
   try:os.chmod(pempath,0o600)
   except OSError:pass
  numbers=key.public_key().public_numbers()
  wire=b"\x04"+numbers.x.to_bytes(32,"big")+numbers.y.to_bytes(32,"big")
  return base64.urlsafe_b64encode(wire).rstrip(b"=").decode(),str(pempath)

def valid(sub):
 if not isinstance(sub,dict):return False
 endpoint=sub.get("endpoint"); k=sub.get("keys")
 if not isinstance(endpoint,str) or len(endpoint)>1800 or not isinstance(k,dict):return False
 try:p=urlsplit(endpoint)
 except ValueError:return False
 if p.scheme!="https" or p.username or p.password:return False
 try:
  if p.port not in (None,443):return False
 except ValueError:return False
 h=(p.hostname or "").lower()
 allowed=h in ("fcm.googleapis.com","updates.push.services.mozilla.com","web.push.apple.com") or h.endswith(".notify.windows.com") or h.endswith(".push.apple.com")
 return allowed and all(isinstance(k.get(n),str) and 20<=len(k[n])<=200 for n in ("p256dh","auth"))

def identifier(sub):return hashlib.sha256(sub["endpoint"].encode()).hexdigest()

@bp.get("/api/push/public-key")
def public_key():
 key,_=keys()
 return jsonify(publicKey=key,ephemeral=True)

@bp.post("/api/push/subscribe")
def subscribe():
 sub=request.get_json(silent=True)
 if not valid(sub):return jsonify(error="Suscripcion no valida"),400
 compact={"endpoint":sub["endpoint"],"keys":{"p256dh":sub["keys"]["p256dh"],"auth":sub["keys"]["auth"]}}
 with lock,sqlite3.connect(dbpath) as db:
  db.execute("INSERT OR REPLACE INTO subscriptions(id,content) VALUES (?,?)",(identifier(compact),json.dumps(compact)))
 return jsonify(ok=True)

@bp.post("/api/push/unsubscribe")
def unsubscribe():
 data=request.get_json(silent=True) or {}
 endpoint=data.get("endpoint")
 if not isinstance(endpoint,str) or not endpoint:return jsonify(error="Falta endpoint"),400
 with lock,sqlite3.connect(dbpath) as db:
  db.execute("DELETE FROM subscriptions WHERE id=?",(hashlib.sha256(endpoint.encode()).hexdigest(),))
 return jsonify(ok=True)

def send_demo(payload=None):
 from pywebpush import webpush,WebPushException
 _,keypath=keys()
 with lock,sqlite3.connect(dbpath) as db:
  subscriptions=[json.loads(x[0]) for x in db.execute("SELECT content FROM subscriptions")]
 payload=json.dumps(payload or {"title":"SERVAMAR - Notificacion de prueba","body":"Aviso de prueba sin datos de clientes."})
 accepted=0
 failed=0
 for sub in subscriptions:
  try:
   webpush(subscription_info=sub,data=payload,vapid_private_key=keypath,vapid_claims={"sub":"https://servamar-demo-gratis-2y03.onrender.com"},ttl=90)
   accepted+=1
  except WebPushException as e:
   failed+=1
   if getattr(getattr(e,"response",None),"status_code",0) in (404,410):
    with lock,sqlite3.connect(dbpath) as db:db.execute("DELETE FROM subscriptions WHERE id=?",(identifier(sub),))
  except Exception:failed+=1
 return {"accepted":accepted,"failed":failed,"subscribers":len(subscriptions)}

@bp.post("/api/push/test")
def test_push():
 with sqlite3.connect(dbpath) as db:count=db.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0]
 if not count:return jsonify(error="Activa avisos primero"),409
 threading.Thread(target=lambda:(time.sleep(12),send_demo()),daemon=True).start()
 return jsonify(ok=True,subscribers=count,message="Aviso programado para dentro de 12 segundos. Puedes cerrar la pestana.")

# Only the authenticated scheduled request may run this endpoint; app.before_request
# verifies HTTP Basic credentials over HTTPS for every non-health-check route.
@bp.post("/api/push/daily-check")
def daily_check():
 from app import planned_alerts_for_day
 today=datetime.now(ZoneInfo("America/Guatemala")).date()
 day=today.isoformat()
 with lock,sqlite3.connect(dbpath) as db:
  db.execute("BEGIN IMMEDIATE")
  previous=db.execute("SELECT status,count,recipients FROM daily_delivery WHERE day=?",(day,)).fetchone()
  if previous and previous[0]=="sent":
   return jsonify(ok=True,date=day,already_sent=True,alerts=previous[1],accepted=previous[2])
  plan=planned_alerts_for_day(today)
  alerts=int(plan["count"])
  if not alerts:
   return jsonify(ok=True,date=day,alerts=0,accepted=0,already_sent=False,note="No hay vencimientos programados hoy")
  # Do not expose vessel names, captain details or permit IDs via notifications.
  categories={}
  for item in plan["items"]:
   category=item.get("category","vencimiento")
   categories[category]=categories.get(category,0)+1
  body="Avisos administrativos: "+str(alerts)+" plazo(s) hoy. Abre SERVAMAR para revisar."
  result=send_demo({"title":"SERVAMAR - Recordatorios administrativos","body":body})
  if result["accepted"]:
   db.execute("INSERT OR REPLACE INTO daily_delivery(day,status,count,recipients,completed_at) VALUES(?,?,?,?,?)",
     (day,"sent",alerts,result["accepted"],datetime.now(ZoneInfo("America/Guatemala")).isoformat()))
  return jsonify(ok=bool(result["accepted"]),date=day,alerts=alerts,categories=categories,
     accepted=result["accepted"],failed=result["failed"],subscribers=result["subscribers"],
     already_sent=False,
     warning=None if result["accepted"] else "No se pudieron enviar notificaciones; suscripciones temporales posiblemente perdidas"),(200 if result["accepted"] else 503)
