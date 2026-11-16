"""V76: conservative parity gate for SQLite -> PostgreSQL projections.

Read-only comparison; any uncertainty blocks activation. No DB writes.
"""
from datetime import date,timedelta
from operational_pg_projection import project_permit,as_date

HISTORICAL_KINDS=frozenset(("salida_archivo","retorno_archivo","ampliacion_archivo","deposito_archivo"))
CONFIRMED_EXIT_KINDS=frozenset(("salida","salida_temporal"))
CONFIRMED_RETURN_KINDS=frozenset(("retorno",))
def assess_case(vessel,movements,legacy=None,today=None):
 """Return an explicit PASS/REVIEW/BLOCK decision, never an authorization."""
 reasons=[]
 stage=vessel.get("stage")
 if stage in ("revision",None):
  reasons.append("Etapa no confirmada o pendiente de revisión")
 historical=[m for m in movements if m.get("kind") in HISTORICAL_KINDS]
 if historical:
  reasons.append("Movimientos históricos importados requieren revisión documental")
 if any(m.get("kind") in ("salida_archivo","retorno_archivo") and not m.get("event_date") for m in movements):
  reasons.append("Fecha histórica ausente; no inferir retorno ni salida")
 if stage=="deposito" and any(m.get("kind") in CONFIRMED_EXIT_KINDS for m in movements):
  reasons.append("Salida durante depósito requiere revisión")
 try:
  projection=project_permit(vessel,[m for m in movements if m.get("kind") not in HISTORICAL_KINDS],today)
 except (ValueError,TypeError,OverflowError) as exc:
  return {"decision":"BLOCK","reasons":["Proyección no calculable: "+str(exc)],"projection":None}
 if projection.get("warnings"):
  reasons.extend(projection["warnings"])
 # Preserve the historical expiry in the file, even when a candidate differs.
 recorded=as_date(vessel.get("expiry_date"))
 if recorded and projection.get("expiry_date"):
  computed=as_date(projection["expiry_date"])
  # Do not mistake a documented temporary-return adjustment for a mismatch.
  if projection.get("days_added",0)==0 and computed!=recorded:
   reasons.append("Vencimiento proyectado difiere del expediente")
 if legacy is not None:
  for field in ("stage","expiry_date","operational_date","days_added"):
   if field not in legacy:continue
   expected=legacy[field]
   actual=projection.get(field)
   if field in ("expiry_date","operational_date"):
    expected=as_date(expected).isoformat() if expected else None
   if expected!=actual:
    reasons.append(f"Diferencia SQLite/PostgreSQL en {field}: {expected!s} != {actual!s}")
 decision="REVIEW" if reasons else "PASS"
 return {"decision":decision,"reasons":sorted(set(reasons)),"projection":projection}

def audit_batch(cases,today=None):
 """Fail closed: not safe to cut over if ANY case needs review."""
 results=[]
 for case in cases:
  results.append(assess_case(case["vessel"],case.get("movements",[]),case.get("legacy"),today))
 counts={k:sum(r["decision"]==k for r in results) for k in ("PASS","REVIEW","BLOCK")}
 return {"ready_for_cutover":bool(results) and counts["REVIEW"]==0 and counts["BLOCK"]==0,
         "counts":counts,"cases":results,
         "note":"Una comparación satisfactoria no sustituye validación de documentos, respaldos y recuperación"}
