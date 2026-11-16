"""V75: deterministic, READ-ONLY permit projections for PostgreSQL sandbox rows.

Does not authorize administrative permits, write to Neon, or replace app.py
business logic. Source data must already be confirmed by an operator.
"""
from datetime import date,timedelta
import calendar

def as_date(value):
 if value is None or value=="":return None
 if isinstance(value,date):return value
 return date.fromisoformat(str(value))
def months_after(d,months):
 index=d.year*12+d.month-1+months
 year,month=divmod(index,12)
 return date(year,month+1,min(d.day,calendar.monthrange(year,month+1)[1]))
def initial_expiry(entry):
 return as_date(entry)+timedelta(days=90)
def extended_expiry(entry):
 # Extension is nine calendar months after the initial 90-day deadline.
 return months_after(initial_expiry(entry),9)
def deposit_expiry(deposit_entry):
 return months_after(as_date(deposit_entry),12)

def project_permit(vessel,movements,today=None):
 """Calculate a PREVIEW; never change or imply confirmation of vessel.stage.

 A confirmed extension uses its stored expiry if present; otherwise the
 calculation is only a candidate for manual verification. Historical exit
 events are not silently treated as confirmed manual returns.
 """
 today=as_date(today) or date.today()
 stage=vessel.get("stage","ingreso")
 entry=as_date(vessel.get("start_date"))
 stored=as_date(vessel.get("expiry_date"))
 warnings=[]
 if stage=="deposito":
  deposits=[as_date(m.get("event_date")) for m in movements if m.get("kind")=="deposito"]
  deposits=[d for d in deposits if d]
  anchor=max(deposits) if deposits else entry
  candidate=deposit_expiry(anchor) if anchor else None
 elif stage=="ampliacion":
  candidate=extended_expiry(entry) if entry else None
 elif stage=="ingreso":
  candidate=initial_expiry(entry) if entry else None
 else:
  candidate=None
 expiry=stored or candidate
 if stored and candidate and stored!=candidate:
  warnings.append("La fecha registrada difiere del cálculo base; revisar antes de confirmar")
 if not stored and candidate:
  warnings.append("Vencimiento calculado sin documento confirmado")
 if stage=="deposito" and any(m.get("kind") in ("salida","salida_temporal") for m in movements):
  warnings.append("Salida registrada durante depósito: revisar expediente")
 if stage in ("cierre","cierre_automatico"):
  return {"stage":"cierre","expiry_date":stored.isoformat() if stored else None,
          "operational_date":None,"days_added":0,"warnings":warnings}
 periods=[];open_exit=None;days_added=0;closure=False
 ordered=sorted(enumerate(movements),key=lambda p:(as_date(p[1].get("event_date")) or date.max,p[0]))
 for _,m in ordered:
  kind=m.get("kind")
  d=as_date(m.get("event_date"))
  if not d:continue
  if kind in ("salida","salida_temporal"):
   if stage=="deposito":continue
   if open_exit is not None:
    warnings.append("Segunda salida sin retorno: revisar")
    continue
   open_exit=d
  elif kind=="retorno":
   if open_exit is None:
    warnings.append("Retorno sin salida: revisar")
    continue
   away=(d-open_exit).days
   if away<0:
    warnings.append("Retorno anterior a salida: revisar")
    continue
   periods.append({"departure":open_exit.isoformat(),"return":d.isoformat(),"days_away":away})
   if away>=90:
    closure=True
    warnings.append("Retorno fuera de plazo: revisar cierre")
   else:
    days_added+=away
   open_exit=None
  elif kind in ("cierre","cierre_automatico"):
   closure=True
 if open_exit is not None:
  outside=max(0,(today-open_exit).days)
  deadline=open_exit+timedelta(days=90)
  if outside>=90:closure=True
  return {"stage":"cierre" if closure else "salida_temporal",
          "expiry_date":expiry.isoformat() if expiry else None,
          "operational_date":deadline.isoformat(),"days_out":outside,
          "days_added":days_added,"periods":periods,"warnings":warnings}
 if expiry and days_added:expiry+=timedelta(days=days_added)
 return {"stage":"cierre" if closure else stage,
         "expiry_date":expiry.isoformat() if expiry else None,
         "operational_date":None if closure or not expiry else expiry.isoformat(),
         "days_added":days_added,"periods":periods,"warnings":warnings}

def project_sandbox(connection,vessel_id,today=None):
 """Reads only V74 sandbox tables; never touches operational/demo/staging data."""
 row=connection.execute("""SELECT id,stage,start_date,expiry_date
 FROM v74_sandbox_vessels WHERE id=%s""",(vessel_id,)).fetchone()
 if not row:raise ValueError("Embarcación de prueba inexistente")
 vessel=dict(zip(("id","stage","start_date","expiry_date"),row))
 rows=connection.execute("""SELECT kind,event_date,expiry_date,description
 FROM v74_sandbox_movements WHERE vessel_id=%s ORDER BY event_date,id""",(vessel_id,)).fetchall()
 movements=[dict(zip(("kind","event_date","expiry_date","description"),r)) for r in rows]
 return project_permit(vessel,movements,today)
