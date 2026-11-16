"""V77/V78: read-only SQLite versus Neon staging row comparison.

Input JSON is a trusted export of the isolated Neon staging tables.
The report never authorizes production cutover.
"""
import argparse,json,sqlite3
from collections import Counter
from pathlib import Path
TABLES=('vessels','history','alert_settings','alert_log','windows_notice_log','permit_documents','edit_audit','movement_before_state','movement_edit_audit','movement_deletion_audit')
def read_sqlite(path):
 with sqlite3.connect(f'file:{Path(path).resolve()}?mode=ro',uri=True) as db:
  db.row_factory=sqlite3.Row
  if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
   raise ValueError('SQLite integrity_check failed')
  return {table:[dict(r) for r in db.execute('SELECT * FROM "'+table+'"')] for table in TABLES}
def compare(source,staged):
 differences=[]
 for table in TABLES:
  left=source.get(table,[]);right=staged.get(table,[])
  if len(left)!=len(right):
   differences.append({'table':table,'field':'row_count','sqlite':len(left),'neon':len(right)})
  def canonical(rows):
   return Counter(json.dumps(row,sort_keys=True,ensure_ascii=False,default=str) for row in rows)
  if canonical(left)!=canonical(right):
   differences.append({'table':table,'field':'row_content','sqlite_rows':len(left),'neon_rows':len(right)})
 vessel_details=[]
 sqlite_by_id={v['id']:v for v in source.get('vessels',[])}
 neon_by_id={v['id']:v for v in staged.get('vessels',[])}
 for vessel_id in sorted(set(sqlite_by_id)|set(neon_by_id)):
  a=sqlite_by_id.get(vessel_id);b=neon_by_id.get(vessel_id)
  changed=[] if a is None or b is None else sorted(k for k in set(a)|set(b) if a.get(k)!=b.get(k))
  vessel_details.append({'id':vessel_id,'declaration':(a or b).get('declaration'),
                         'match':a==b,'different_fields':changed,
                         'missing_in':'neon' if b is None else 'sqlite' if a is None else None})
 return {'ready_for_cutover':False,'rows_identical':not differences,
         'differences':differences,'vessels':vessel_details,
         'note':'Comparación de respaldo, no valida permisos históricos ni respaldos automáticos.'}
def main():
 parser=argparse.ArgumentParser()
 parser.add_argument('sqlite_file');parser.add_argument('neon_staging_json')
 parser.add_argument('--output',default='servamar_parity_report.json')
 args=parser.parse_args()
 result=compare(read_sqlite(args.sqlite_file),json.loads(Path(args.neon_staging_json).read_text(encoding='utf8')))
 Path(args.output).write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf8')
 print(json.dumps({'rows_identical':result['rows_identical'],'differences':len(result['differences']),'ready_for_cutover':False},ensure_ascii=False))
if __name__=='__main__':main()
