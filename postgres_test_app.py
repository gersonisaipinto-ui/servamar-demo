"""V89: standalone SERVAMAR PostgreSQL TEST console.

Never import or modify the production Flask app. Deploy separately with
SERVAMAR_PG_TEST_MODE=YES, SERVAMAR_PG_TEST_DATABASE_URL pointing to the
dedicated Neon testing branch and SERVAMAR_PG_TEST_PASSWORD (>=16 chars).
Only fictitious records are permitted. No email or push integrations.
"""
import hmac,os,re
from datetime import date
from functools import wraps
from flask import Flask,request,jsonify,Response
app=Flask(__name__)
def configured():
 return (os.getenv("SERVAMAR_PG_TEST_MODE")=="YES" and
         len(os.getenv("SERVAMAR_PG_TEST_PASSWORD",""))>=16 and
         bool(os.getenv("SERVAMAR_PG_TEST_DATABASE_URL")) and
         os.getenv("SERVAMAR_PG_TEST_BRANCH_ID")=="br-green-band-arsmtoxc")
def authorized():
 auth=request.authorization
 return bool(auth and hmac.compare_digest(auth.username or "",os.getenv("SERVAMAR_PG_TEST_USERNAME","servamar-test")) and hmac.compare_digest(auth.password or "",os.getenv("SERVAMAR_PG_TEST_PASSWORD","")))
def protected(fn):
 @wraps(fn)
 def wrapped(*args,**kwargs):
  if not configured():return jsonify(error="PostgreSQL test console disabled"),503
  if not authorized():return Response("Authentication required",401,{"WWW-Authenticate":'Basic realm="SERVAMAR TEST"'})
  if os.getenv("SERVAMAR_PG_TEST_REQUIRE_HTTPS","YES")=="YES" and request.headers.get("X-Forwarded-Proto","https").split(",")[0].strip()!="https":
   return jsonify(error="HTTPS required"),403
  return fn(*args,**kwargs)
 return wrapped
def connection():
 import psycopg
 return psycopg.connect(os.environ["SERVAMAR_PG_TEST_DATABASE_URL"],connect_timeout=8)
def ensure_test_declaration(declaration):
 if not re.fullmatch(r"ST-(?:DEMO|TEST)-[A-Z0-9-]{1,40}",declaration or ""):
  raise ValueError("Solo se permiten registros ficticios ST-DEMO- o ST-TEST-")
def parse_date(value):
 if value is None or value=="":return None
 return date.fromisoformat(value)
@app.get("/healthz")
def health():
 return jsonify(service="servamar-postgres-test",configured=configured())
@app.get("/")
@protected
def home():
 return Response("""<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SERVAMAR | PostgreSQL pruebas</title><style>body{font:16px system-ui;margin:24px auto;max-width:900px;padding:0 14px}input,select,button{font:inherit;padding:8px;margin:4px}table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #ccc;padding:8px;text-align:left}small{color:#666}</style><h1>SERVAMAR · Base PostgreSQL de pruebas</h1><p><strong>SOLO DATOS FICTICIOS.</strong> No es la base operativa de clientes.</p><form id="new"><input name="declaration" placeholder="ST-TEST-004" required><input name="name" placeholder="Nombre de prueba" required><input name="captain" placeholder="Capitán ficticio" required><input name="start_date" type="date"><input name="expiry_date" type="date"><button>Agregar embarcación</button></form><p id="message" role="status"></p><table><thead><tr><th>Registro</th><th>Embarcación</th><th>Capitán</th><th>Etapa</th><th>Vencimiento</th></tr></thead><tbody id="rows"></tbody></table><script>async function refresh(){const r=await fetch('/api/test/vessels');const j=await r.json();document.querySelector('#rows').replaceChildren(...j.vessels.map(v=>{const tr=document.createElement('tr');[v.declaration,v.name,v.captain,v.stage,v.expiry_date||''].forEach(s=>{const td=document.createElement('td');td.textContent=s;tr.append(td)});return tr}))}document.querySelector('#new').onsubmit=async e=>{e.preventDefault();const body=Object.fromEntries(new FormData(e.target));const r=await fetch('/api/test/vessels',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const j=await r.json();document.querySelector('#message').textContent=r.ok?'Registro ficticio guardado':(j.error||'Error');if(r.ok){e.target.reset();refresh()}};refresh()</script></html>""",mimetype="text/html")
@app.get("/api/test/vessels")
@protected
def vessels():
 with connection() as db:
  rows=db.execute("SELECT id,declaration,name,captain,stage,start_date,expiry_date FROM servamar_test.vessels ORDER BY expiry_date NULLS LAST,id").fetchall()
 return jsonify(vessels=[dict(zip(("id","declaration","name","captain","stage","start_date","expiry_date"),[x.isoformat() if isinstance(x,date) else x for x in row])) for row in rows])
@app.post("/api/test/vessels")
@protected
def add_vessel():
 try:
  data=request.get_json(silent=True) or {}
  declaration=str(data.get("declaration","")).strip().upper()
  ensure_test_declaration(declaration)
  name=str(data.get("name","")).strip();captain=str(data.get("captain","")).strip()
  if not name or not captain or len(name)>200 or len(captain)>200:raise ValueError("Nombre y capitán ficticios requeridos")
  start=parse_date(data.get("start_date"));expiry=parse_date(data.get("expiry_date"))
  if start and expiry and expiry<start:raise ValueError("Vencimiento anterior al ingreso")
  with connection() as db:
   row=db.execute("INSERT INTO servamar_test.vessels(id,declaration,name,captain,stage,start_date,expiry_date,validated,notes) VALUES ((SELECT COALESCE(MAX(id),0)+1 FROM servamar_test.vessels),%s,%s,%s,'ingreso',%s,%s,FALSE,'DATOS FICTICIOS: PRUEBA GRATUITA') RETURNING id",(declaration,name,captain,start,expiry)).fetchone()
  return jsonify(id=row[0],created=True),201
 except (ValueError,TypeError) as exc:return jsonify(error=str(exc)),400
 except Exception as exc:
  if getattr(exc,"sqlstate",None)=="23505":return jsonify(error="Registro de prueba duplicado"),409
  raise
@app.get("/api/test/vessels/<int:vessel_id>/alerts")
@protected
def alerts(vessel_id):
 with connection() as db:
  rows=db.execute("SELECT days_before,enabled FROM servamar_test.alert_settings WHERE vessel_id=%s ORDER BY days_before DESC",(vessel_id,)).fetchall()
 return jsonify(alerts=[{"days_before":r[0],"enabled":r[1]} for r in rows])
@app.get("/api/test/vessels/<int:vessel_id>/movements")
@protected
def movements(vessel_id):
 with connection() as db:
  rows=db.execute("SELECT id,kind,event_date,expiry_date,description FROM servamar_test.history WHERE vessel_id=%s ORDER BY event_date,id",(vessel_id,)).fetchall()
 return jsonify(movements=[{"id":r[0],"kind":r[1],"event_date":r[2].isoformat() if r[2] else None,"expiry_date":r[3].isoformat() if r[3] else None,"description":r[4]} for r in rows])
@app.post("/api/test/vessels/<int:vessel_id>/movements")
@protected
def add_movement(vessel_id):
 try:
  data=request.get_json(silent=True) or {}
  kind=str(data.get("kind","")).strip()
  if kind not in ("ingreso","ampliacion","deposito","salida","retorno","cierre"):raise ValueError("Tipo de movimiento inválido")
  event_date=parse_date(data.get("event_date"))
  if not event_date:raise ValueError("Fecha del movimiento requerida")
  with connection() as db:
   vessel=db.execute("SELECT declaration FROM servamar_test.vessels WHERE id=%s",(vessel_id,)).fetchone()
   if not vessel:return jsonify(error="Embarcación inexistente"),404
   ensure_test_declaration(vessel[0])
   row=db.execute("INSERT INTO servamar_test.history(id,vessel_id,kind,event_date,description) VALUES ((SELECT COALESCE(MAX(id),0)+1 FROM servamar_test.history),%s,%s,%s,%s) RETURNING id",(vessel_id,kind,event_date,"Movimiento ficticio de prueba")).fetchone()
  return jsonify(id=row[0],created=True),201
 except (ValueError,TypeError) as exc:return jsonify(error=str(exc)),400
if __name__=="__main__":
 if not configured():raise SystemExit("Test configuration incomplete")
 app.run(host="127.0.0.1",port=int(os.getenv("PORT","8790")),debug=False)
