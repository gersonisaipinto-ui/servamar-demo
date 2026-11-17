"""V87: conservative wrapper preventing expiry double-count in preview.

A stored permit expiry may already contain return-day adjustments. Never
add historical days again without explicit, documented provenance.
"""
from datetime import date,timedelta
from operational_pg_projection import project_permit,as_date,initial_expiry,extended_expiry

def safe_projection(vessel,movements,today=None,expiry_provenance=None):
 result=project_permit(vessel,movements,today)
 warnings=list(result.get("warnings",[]))
 stored=as_date(vessel.get("expiry_date"))
 days=result.get("days_added",0)
 if stored and days:
  if expiry_provenance=="includes_return_days":
   result["expiry_date"]=stored.isoformat()
   if result.get("stage") not in ("cierre","salida_temporal"):
    result["operational_date"]=stored.isoformat()
  elif expiry_provenance=="excludes_return_days":
   # Explicit provenance is a prerequisite, not proof of an approved extension.
   pass
  else:
   result["expiry_date"]=stored.isoformat()
   if result.get("stage") not in ("cierre","salida_temporal"):
    result["operational_date"]=stored.isoformat()
   warnings.append("BLOQUEO: vencimiento registrado puede incluir días de retorno; no sumar sin procedencia documentada")
   result["needs_review"]=True
 if vessel.get("stage")=="ampliacion" and vessel.get("start_date"):
  entry=as_date(vessel["start_date"])
  day90plus9=extended_expiry(entry)
  anniversary=date(entry.year+1,entry.month,entry.day) if not(entry.month==2 and entry.day==29) else date(entry.year+1,2,28)
  if day90plus9!=anniversary:
   warnings.append("BLOQUEO: 90 días + 9 meses difiere del aniversario anual; confirmar criterio administrativo")
   result["needs_review"]=True
 result["warnings"]=warnings
 result["ready_for_operational_use"]=not result.get("needs_review",False) and not warnings and not days
 return result
