"""SERVAMAR Web Push demo: optional PostgreSQL persistence, no vessel data in pushes."""
import base64
import hashlib
import json
import os
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, request

bp = Blueprint("servamar_push_demo", __name__)
lock = threading.RLock()
dbpath = None
pempath = None
PG_URL = os.environ.get("SERVAMAR_PUSH_DATABASE_URL", "").strip()


def pg_connect():
    import psycopg
    return psycopg.connect(PG_URL, connect_timeout=10)


def init_push(app, data_dir):
    global dbpath, pempath
    dbpath = Path(data_dir) / "webpush_demo.sqlite3"
    pempath = Path(data_dir) / "webpush_demo_vapid.pem"
    if PG_URL:
        with pg_connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS servamar_push_subscriptions
                (id TEXT PRIMARY KEY, content TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS servamar_push_settings
                (id TEXT PRIMARY KEY, pem TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS servamar_push_daily_delivery
                (day TEXT PRIMARY KEY, status TEXT NOT NULL, count INTEGER NOT NULL,
                 recipients INTEGER NOT NULL, completed_at TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS servamar_push_daily_targets
                (day TEXT NOT NULL, sub_id TEXT NOT NULL, PRIMARY KEY(day,sub_id))""")
    else:
        with sqlite3.connect(dbpath) as db:
            db.execute("CREATE TABLE IF NOT EXISTS subscriptions (id TEXT PRIMARY KEY, content TEXT NOT NULL)")
            db.execute("""CREATE TABLE IF NOT EXISTS daily_delivery
                (day TEXT PRIMARY KEY, status TEXT NOT NULL, count INTEGER NOT NULL,
                 recipients INTEGER NOT NULL, completed_at TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS daily_targets
                (day TEXT NOT NULL, sub_id TEXT NOT NULL, PRIMARY KEY(day,sub_id))""")
    app.register_blueprint(bp)
    # Programación única solicitada para el 13/11/2026 a las 13:50 GT.
    threading.Thread(target=one_time_1350, daemon=True, name='servamar-prueba-1350').start()


def keys():
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    with lock:
        if PG_URL:
            with pg_connect() as db:
                row = db.execute("SELECT pem FROM servamar_push_settings WHERE id='vapid'").fetchone()
                if row:
                    pem = row[0].encode()
                else:
                    new = ec.generate_private_key(ec.SECP256R1())
                    pem = new.private_bytes(serialization.Encoding.PEM,
                                            serialization.PrivateFormat.PKCS8,
                                            serialization.NoEncryption())
                    db.execute("""INSERT INTO servamar_push_settings(id,pem) VALUES('vapid',%s)
                        ON CONFLICT (id) DO NOTHING""", (pem.decode(),))
                    saved = db.execute("SELECT pem FROM servamar_push_settings WHERE id='vapid'").fetchone()
                    pem = saved[0].encode()
            if not pempath.exists() or pempath.read_bytes() != pem:
                pempath.write_bytes(pem)
                os.chmod(pempath, 0o600)
        elif pempath.exists():
            pem = pempath.read_bytes()
        else:
            new = ec.generate_private_key(ec.SECP256R1())
            pem = new.private_bytes(serialization.Encoding.PEM,
                                    serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption())
            with pempath.open("xb") as out:
                out.write(pem)
            os.chmod(pempath, 0o600)
        key = serialization.load_pem_private_key(pem, password=None)
        point = key.public_key().public_numbers()
        wire = b"\x04" + point.x.to_bytes(32, "big") + point.y.to_bytes(32, "big")
        return base64.urlsafe_b64encode(wire).rstrip(b"=").decode(), str(pempath)


def valid(sub):
    if not isinstance(sub, dict):
        return False
    endpoint, value = sub.get("endpoint"), sub.get("keys")
    if not isinstance(endpoint, str) or len(endpoint) > 1800 or not isinstance(value, dict):
        return False
    try:
        url = urlsplit(endpoint)
        if url.scheme != "https" or url.username or url.password or url.port not in (None, 443):
            return False
    except ValueError:
        return False
    hostname = (url.hostname or "").lower()
    allowed = (hostname in ("fcm.googleapis.com", "updates.push.services.mozilla.com",
                            "web.push.apple.com") or
               hostname.endswith(".notify.windows.com") or
               hostname.endswith(".push.apple.com"))
    return allowed and all(isinstance(value.get(n), str) and 20 <= len(value[n]) <= 200
                           for n in ("p256dh", "auth"))


def identifier(sub):
    return hashlib.sha256(sub["endpoint"].encode()).hexdigest()


def subscriptions():
    if PG_URL:
        with pg_connect() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT content FROM servamar_push_subscriptions")]
    with sqlite3.connect(dbpath) as db:
        return [json.loads(r[0]) for r in db.execute("SELECT content FROM subscriptions")]


def upsert_subscription(sub):
    payload = json.dumps(sub)
    with lock:
        if PG_URL:
            with pg_connect() as db:
                db.execute("""INSERT INTO servamar_push_subscriptions(id,content) VALUES(%s,%s)
                    ON CONFLICT (id) DO UPDATE SET content=excluded.content""",
                           (identifier(sub), payload))
        else:
            with sqlite3.connect(dbpath) as db:
                db.execute("INSERT OR REPLACE INTO subscriptions(id,content) VALUES(?,?)",
                           (identifier(sub), payload))


def remove_subscription(endpoint):
    key = hashlib.sha256(endpoint.encode()).hexdigest()
    with lock:
        if PG_URL:
            with pg_connect() as db:
                db.execute("DELETE FROM servamar_push_subscriptions WHERE id=%s", (key,))
        else:
            with sqlite3.connect(dbpath) as db:
                db.execute("DELETE FROM subscriptions WHERE id=?", (key,))


def daily_previous(day):
    if PG_URL:
        with pg_connect() as db:
            return db.execute("""SELECT status,count,recipients FROM servamar_push_daily_delivery
                WHERE day=%s""", (day,)).fetchone()
    with sqlite3.connect(dbpath) as db:
        return db.execute("SELECT status,count,recipients FROM daily_delivery WHERE day=?", (day,)).fetchone()


def already_delivered(day, sub_id):
    if PG_URL:
        with pg_connect() as db:
            return bool(db.execute("""SELECT 1 FROM servamar_push_daily_targets
                WHERE day=%s AND sub_id=%s""", (day, sub_id)).fetchone())
    with sqlite3.connect(dbpath) as db:
        return bool(db.execute("SELECT 1 FROM daily_targets WHERE day=? AND sub_id=?",
                               (day, sub_id)).fetchone())


def record_target(day, sub_id):
    with lock:
        if PG_URL:
            with pg_connect() as db:
                db.execute("""INSERT INTO servamar_push_daily_targets(day,sub_id)
                    VALUES(%s,%s) ON CONFLICT DO NOTHING""", (day, sub_id))
        else:
            with sqlite3.connect(dbpath) as db:
                db.execute("INSERT OR IGNORE INTO daily_targets(day,sub_id) VALUES(?,?)",
                           (day, sub_id))


def record_day(day, count, recipients):
    timestamp = datetime.now(ZoneInfo("America/Guatemala")).isoformat()
    with lock:
        if PG_URL:
            with pg_connect() as db:
                db.execute("""INSERT INTO servamar_push_daily_delivery
                    (day,status,count,recipients,completed_at) VALUES(%s,'sent',%s,%s,%s)
                    ON CONFLICT(day) DO UPDATE SET status='sent',
                    count=excluded.count, recipients=excluded.recipients,
                    completed_at=excluded.completed_at""", (day, count, recipients, timestamp))
        else:
            with sqlite3.connect(dbpath) as db:
                db.execute("""INSERT OR REPLACE INTO daily_delivery
                    (day,status,count,recipients,completed_at) VALUES(?,'sent',?,?,?)""",
                           (day, count, recipients, timestamp))


@bp.get("/api/push/public-key")
def public_key():
    value, _ = keys()
    return jsonify(publicKey=value, ephemeral=not bool(PG_URL))


@bp.post("/api/push/subscribe")
def subscribe():
    sub = request.get_json(silent=True)
    if not valid(sub):
        return jsonify(error="Suscripción no válida"), 400
    compact = {"endpoint": sub["endpoint"],
               "keys": {"p256dh": sub["keys"]["p256dh"], "auth": sub["keys"]["auth"]}}
    upsert_subscription(compact)
    return jsonify(ok=True, persistent=bool(PG_URL))


@bp.post("/api/push/unsubscribe")
def unsubscribe():
    data = request.get_json(silent=True) or {}
    endpoint = data.get("endpoint")
    if not isinstance(endpoint, str) or not endpoint:
        return jsonify(error="Falta endpoint"), 400
    remove_subscription(endpoint)
    return jsonify(ok=True)


def send_demo(payload=None, day=None):
    from pywebpush import webpush, WebPushException
    _, keypath = keys()
    saved = subscriptions()
    content = json.dumps(payload or
                         {"title": "SERVAMAR - Notificación de prueba",
                          "body": "Aviso de prueba sin datos de clientes."})
    accepted, failed, skipped = 0, 0, 0
    for sub in saved:
        sub_id = identifier(sub)
        if day and already_delivered(day, sub_id):
            skipped += 1
            continue
        try:
            webpush(subscription_info=sub, data=content,
                    vapid_private_key=keypath,
                    vapid_claims={"sub": "https://servamar-demo-gratis-2y03.onrender.com"},
                    ttl=90)
            accepted += 1
            if day:
                record_target(day, sub_id)
        except WebPushException as exc:
            failed += 1
            if getattr(getattr(exc, "response", None), "status_code", 0) in (404, 410):
                remove_subscription(sub["endpoint"])
        except Exception:
            failed += 1
    return {"accepted": accepted, "failed": failed, "skipped": skipped,
            "subscribers": len(saved)}


@bp.post("/api/push/test")
def test_push():
    count = len(subscriptions())
    if not count:
        return jsonify(error="Activa avisos primero"), 409
    threading.Thread(target=lambda: (time.sleep(12), send_demo()), daemon=True).start()
    return jsonify(ok=True, subscribers=count,
                   message="Aviso programado para dentro de 12 segundos. Puedes cerrar la pestaña.")


@bp.post("/api/push/daily-check")
def daily_check():
    # app.before_request enforces HTTP Basic credentials and HTTPS.
    # This endpoint uses existing fictitious vessels; never sends vessel data.
    from app import planned_alerts_for_day
    today = datetime.now(ZoneInfo("America/Guatemala")).date()
    day = today.isoformat()
    with lock:
        previous = daily_previous(day)
        if previous and previous[0] == "sent":
            return jsonify(ok=True, date=day, already_sent=True,
                           alerts=previous[1], accepted=previous[2])
        plan = planned_alerts_for_day(today)
        count = int(plan["count"])
        if not count:
            return jsonify(ok=True, date=day, alerts=0, accepted=0,
                           already_sent=False, note="No hay vencimientos programados hoy")
        categories = {}
        for item in plan["items"]:
            category = item.get("category", "vencimiento")
            categories[category] = categories.get(category, 0) + 1
        payload = {
            "title": "SERVAMAR - Recordatorios administrativos",
            "body": f"Hay {count} plazo(s) por revisar hoy. Abre SERVAMAR."
        }
        result = send_demo(payload, day=day)
        # Mark complete only if there was at least one subscription and all
        # current targets were either delivered or recorded previously.
        success = result["subscribers"] > 0 and result["failed"] == 0
        if success:
            record_day(day, count, result["accepted"] + result["skipped"])
        return jsonify(ok=success, date=day, alerts=count,
                       categories=categories, accepted=result["accepted"],
                       skipped=result["skipped"], failed=result["failed"],
                       subscribers=result["subscribers"], already_sent=False,
                       persistent=bool(PG_URL),
                       warning=None if success else "No se confirmaron todos los envíos de Web Push"), (200 if success else 503)

def one_time_1350():
    """Enviar una sola prueba el 13/11/2026 a las 13:50 Guatemala."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("America/Guatemala")
    target = datetime(2026, 11, 13, 13, 50, 0, tzinfo=tz)
    now = datetime.now(tz)
    # No emitir fuera de una ventana de prueba de 90 segundos.
    if now > target.replace(minute=51, second=30):
        return
    delay = (target - now).total_seconds()
    if delay > 0:
        time.sleep(delay)
    key = "test-2026-11-13-1350"
    with lock:
        if daily_previous(key):
            return
        result = send_demo({
            "title": "SERVAMAR - Prueba programada 13:50",
            "body": "Aviso automático de prueba a las 13:50, hora de Guatemala. Sin datos de clientes."
        }, day=key)
        # Registramos solo los avisos aceptados; el proveedor puede tardar en mostrarlos.
        if result["accepted"] > 0 and result["failed"] == 0:
            record_day(key, 1, result["accepted"])
