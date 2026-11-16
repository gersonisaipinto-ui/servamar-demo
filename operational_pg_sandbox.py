"""SERVAMAR V74: isolated PostgreSQL CRUD sandbox.

Never invoked by app.py. Uses dedicated v74_* tables, with no access to the
existing production, demo or operational staging tables. Test data only.
"""
from datetime import date
import json
import re

SCHEMA = (
 """CREATE TABLE IF NOT EXISTS v74_sandbox_vessels (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  declaration TEXT NOT NULL,
  registration_number TEXT NOT NULL DEFAULT '',
  name TEXT NOT NULL,
  captain TEXT NOT NULL DEFAULT '',
  stage TEXT NOT NULL DEFAULT 'ingreso',
  start_date DATE,
  expiry_date DATE,
  notes TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(declaration,name)
 )""",
 """CREATE TABLE IF NOT EXISTS v74_sandbox_movements (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  vessel_id BIGINT NOT NULL REFERENCES v74_sandbox_vessels(id),
  source_id TEXT,
  kind TEXT NOT NULL,
  event_date DATE NOT NULL,
  expiry_date DATE,
  description TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(source_id,kind)
 )""",
 """CREATE INDEX IF NOT EXISTS v74_sandbox_movements_vessel_date
 ON v74_sandbox_movements(vessel_id,event_date,id)""",
 """CREATE TABLE IF NOT EXISTS v74_sandbox_audit (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  vessel_id BIGINT NOT NULL REFERENCES v74_sandbox_vessels(id),
  movement_id BIGINT,
  operation TEXT NOT NULL,
  before_json JSONB,
  after_json JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
 )""",
)
KINDS = frozenset(("ingreso","ampliacion","deposito","salida_temporal",
                   "retorno","cierre","cierre_automatico"))
STAGES = frozenset(("ingreso","ampliacion","deposito","salida_temporal","cierre"))
def _date(value):
 if value is None or value == "":return None
 if isinstance(value,date):return value
 return date.fromisoformat(str(value))
def validate_vessel(data):
 if not isinstance(data,dict):raise ValueError("Se requiere un objeto de embarcación")
 declaration=str(data.get("declaration","")).strip()
 name=str(data.get("name","")).strip()
 if not declaration or not name:raise ValueError("Declaración y nombre son obligatorios")
 stage=str(data.get("stage","ingreso"))
 if stage not in STAGES:raise ValueError("Etapa desconocida")
 start=_date(data.get("start_date"));expiry=_date(data.get("expiry_date"))
 if start and expiry and expiry < start:raise ValueError("Vencimiento anterior al ingreso")
 return {"declaration":declaration,"registration_number":str(data.get("registration_number","")).strip(),
         "name":name,"captain":str(data.get("captain","")).strip(),"stage":stage,
         "start_date":start,"expiry_date":expiry,"notes":str(data.get("notes","")).strip()}
def validate_movement(data):
 if not isinstance(data,dict):raise ValueError("Se requiere un movimiento")
 kind=str(data.get("kind","")).strip()
 if kind not in KINDS:raise ValueError("Tipo de movimiento desconocido")
 event=_date(data.get("event_date"))
 if event is None:raise ValueError("Fecha del movimiento obligatoria")
 expiry=_date(data.get("expiry_date"))
 if expiry and expiry < event:raise ValueError("Vencimiento anterior al movimiento")
 return {"kind":kind,"event_date":event,"expiry_date":expiry,
         "description":str(data.get("description","")).strip(),
         "source_id":str(data.get("source_id","")).strip() or None}
def _json(data):
 return json.dumps(data,ensure_ascii=False,default=str)
class Sandbox:
 def __init__(self,connection):self.db=connection
 def install(self):
  with self.db.transaction():
   for sql in SCHEMA:self.db.execute(sql)
 def create_vessel(self,data):
  v=validate_vessel(data)
  with self.db.transaction():
   row=self.db.execute("""INSERT INTO v74_sandbox_vessels
    (declaration,registration_number,name,captain,stage,start_date,expiry_date,notes)
    VALUES (%(declaration)s,%(registration_number)s,%(name)s,%(captain)s,%(stage)s,
            %(start_date)s,%(expiry_date)s,%(notes)s) RETURNING id""",v).fetchone()
   vessel_id=row[0]
   self.db.execute("""INSERT INTO v74_sandbox_audit(vessel_id,operation,after_json)
    VALUES (%s,'create_vessel',%s::jsonb)""",(vessel_id,_json(v)))
  return vessel_id
 def update_vessel(self,vessel_id,changes):
  if not isinstance(changes,dict):raise ValueError("Cambios inválidos")
  allowed=set(validate_vessel({"declaration":"x","name":"x"}))
  if not changes or not set(changes).issubset(allowed):
   raise ValueError("Campos de modificación desconocidos")
  with self.db.transaction():
   row=self.db.execute("SELECT declaration,registration_number,name,captain,stage,start_date,expiry_date,notes FROM v74_sandbox_vessels WHERE id=%s FOR UPDATE",(vessel_id,)).fetchone()
   if not row:raise ValueError("Embarcación inexistente")
   current=dict(zip(("declaration","registration_number","name","captain","stage","start_date","expiry_date","notes"),row))
   updated=validate_vessel({**current,**changes})
   self.db.execute("""UPDATE v74_sandbox_vessels SET declaration=%(declaration)s,
    registration_number=%(registration_number)s,name=%(name)s,captain=%(captain)s,
    stage=%(stage)s,start_date=%(start_date)s,expiry_date=%(expiry_date)s,
    notes=%(notes)s WHERE id=%(id)s""",{**updated,"id":vessel_id})
   self.db.execute("""INSERT INTO v74_sandbox_audit(vessel_id,operation,before_json,after_json)
    VALUES (%s,'update_vessel',%s::jsonb,%s::jsonb)""",(vessel_id,_json(current),_json(updated)))
 def add_movement(self,vessel_id,data):
  m=validate_movement(data)
  with self.db.transaction():
   if not self.db.execute("SELECT id FROM v74_sandbox_vessels WHERE id=%s FOR UPDATE",(vessel_id,)).fetchone():
    raise ValueError("Embarcación inexistente")
   movement_id=self.db.execute("""INSERT INTO v74_sandbox_movements
    (vessel_id,source_id,kind,event_date,expiry_date,description)
    VALUES (%(vessel_id)s,%(source_id)s,%(kind)s,%(event_date)s,%(expiry_date)s,
            %(description)s) RETURNING id""",{**m,"vessel_id":vessel_id}).fetchone()[0]
   self.db.execute("""INSERT INTO v74_sandbox_audit(vessel_id,movement_id,operation,after_json)
    VALUES (%s,%s,'add_movement',%s::jsonb)""",(vessel_id,movement_id,_json(m)))
  return movement_id
 def update_movement(self,vessel_id,movement_id,changes):
  if not isinstance(changes,dict) or not changes or not set(changes).issubset({"kind","event_date","expiry_date","description","source_id"}):
   raise ValueError("Campos de movimiento inválidos")
  with self.db.transaction():
   row=self.db.execute("""SELECT source_id,kind,event_date,expiry_date,description
    FROM v74_sandbox_movements WHERE id=%s AND vessel_id=%s FOR UPDATE""",(movement_id,vessel_id)).fetchone()
   if not row:raise ValueError("Movimiento inexistente")
   current=dict(zip(("source_id","kind","event_date","expiry_date","description"),row))
   updated=validate_movement({**current,**changes})
   self.db.execute("""UPDATE v74_sandbox_movements SET source_id=%(source_id)s,
    kind=%(kind)s,event_date=%(event_date)s,expiry_date=%(expiry_date)s,
    description=%(description)s WHERE id=%(id)s AND vessel_id=%(vessel_id)s""",
    {**updated,"id":movement_id,"vessel_id":vessel_id})
   self.db.execute("""INSERT INTO v74_sandbox_audit(vessel_id,movement_id,operation,before_json,after_json)
    VALUES (%s,%s,'update_movement',%s::jsonb,%s::jsonb)""",
    (vessel_id,movement_id,_json(current),_json(updated)))
 def list_vessels(self):
  return self.db.execute("""SELECT id,declaration,registration_number,name,captain,stage,
   start_date,expiry_date,notes FROM v74_sandbox_vessels ORDER BY id""").fetchall()
 def list_movements(self,vessel_id):
  return self.db.execute("""SELECT id,source_id,kind,event_date,expiry_date,description
   FROM v74_sandbox_movements WHERE vessel_id=%s ORDER BY event_date,id""",(vessel_id,)).fetchall()
