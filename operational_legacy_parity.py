"""V79: compare real legacy temporary-exit algorithm with PostgreSQL projection.

Loads the original function's AST without importing the Flask app or touching
production data. Read-only fixture harness; flags differences instead of
silently approving cutover.
"""
import ast
import calendar
import re
from datetime import date,timedelta
from pathlib import Path
from operational_pg_projection import project_permit
from operational_pg_parity_gate import assess_case

def _legacy_function():
 source=Path(__file__).with_name("app.py").read_text(encoding="utf-8")
 module=ast.parse(source)
 function=next(n for n in module.body if isinstance(n,ast.FunctionDef) and n.name=="temporary_exit_summary")
 namespace={
  "date":date,"timedelta":timedelta,
  "requiredate":lambda v: date.fromisoformat(str(v)) if v else None,
  "HISTORICAL_TEMPORARY_KINDS":("salida_archivo","retorno_archivo"),
  "historical_temporary_date":lambda kind,description: _historical_date(kind,description),
 }
 exec(compile(ast.Module(body=[function],type_ignores=[]),"<legacy-temp-exit>","exec"),namespace)
 return namespace["temporary_exit_summary"]
def _historical_date(kind,description):
 label="SALIDA TEMPORAL" if kind=="salida_archivo" else "RETORNO DE SALIDA TEMPORAL"
 match=re.search(re.escape(label)+r"\s*[:\-]?\s*(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})",str(description or "").upper())
 return date(int(match[3]),int(match[2]),int(match[1])) if match else None
def compare_scenario(vessel,movements,today):
 legacy_rows=[{"id":i+1,"kind":m["kind"],"event_date":m.get("event_date"),
               "source_id":m.get("source_id"),"description":m.get("description","")} for i,m in enumerate(movements)]
 legacy=_legacy_function()(None,1,date.fromisoformat(today),legacy_rows)
 modern=project_permit(vessel,movements,today)
 historical=any(m["kind"] in ("salida_archivo","retorno_archivo") for m in movements)
 differences=[]
 if legacy["days_added"]!=modern.get("days_added",0):
  differences.append({"field":"days_added","sqlite":legacy["days_added"],"postgres_projection":modern.get("days_added",0)})
 if legacy["must_close"]!=(modern["stage"]=="cierre") and legacy["currently_away"]:
  differences.append({"field":"must_close","sqlite":legacy["must_close"],"postgres_projection":modern["stage"]=="cierre"})
 if legacy["currently_away"] and legacy["return_deadline"]!=modern.get("operational_date"):
  differences.append({"field":"return_deadline","sqlite":legacy["return_deadline"],"postgres_projection":modern.get("operational_date")})
 return {"differences":differences,"historical_review_required":historical,
         "ready_for_cutover":not differences and not historical and not modern.get("warnings"),
         "legacy":{k:legacy[k] for k in ("days_added","must_close","return_deadline","historical_days_for_review")},
         "projection":modern}
