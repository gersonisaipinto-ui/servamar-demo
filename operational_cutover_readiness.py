"""V85: produce a complete, read-only operational migration readiness report.

No cutover, writes, secret disclosure, or implicit approval.
"""
import json
from operational_staging_readiness import inspect_staging
from operational_staging_adapter import EXPECTED_TABLES

def readiness_report(connection,import_id,sqlite_verified=False,postgres_restore_verified=False,
                     historical_parity_verified=False,external_backup_verified=False,
                     permit_rules_approved=False):
 staged=inspect_staging(connection,import_id)
 gates={
  "staging_consistent":staged["rows"]==staged["vessels"]+staged["history"]+staged["alerts"],
  "sqlite_backup_integrity":bool(sqlite_verified),
  "postgres_restore_test":bool(postgres_restore_verified),
  "historical_parity":bool(historical_parity_verified),
  "external_backup":bool(external_backup_verified),
  "permit_rules_approved":bool(permit_rules_approved),
  "schema_metadata_complete":not staged["missing_table_metadata"],
 }
 return {"import_id":import_id,"gates":gates,"blockers":sorted(k for k,v in gates.items() if not v),
         "ready_for_cutover":all(gates.values()),
         "staging":staged,
         "note":"No database switch is performed. Any unverified gate is false."}
