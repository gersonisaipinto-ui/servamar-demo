"""Reimportación idempotente que preserva datos editados y autorizaciones."""
import json, hashlib
from xlsx_import import extract_any

def ingest(c,payload,commit=False):
    stats={'new_vessels':0,'new_events':0,'existing_events':0,'ambiguous':0,'changed_records_to_review':0,'rows':0}
    def norm(x):return ' '.join(str(x or '').upper().split())
    for typ,items in payload.items():
        for row in items:
            src=row['ID origen'].strip(); dec=row['Declaración'].strip();name=row['Embarcación'].strip()
            if not src or not dec or not name:continue
            stats['rows']+=1
            # Match conservador: pareja exacta, nunca solo ST que puede reutilizarse.
            matches=c.execute('SELECT id FROM vessels WHERE upper(trim(declaration))=? AND upper(trim(name))=?',(norm(dec),norm(name))).fetchall()
            if len(matches)>1:stats['ambiguous']+=1;continue
            if not matches:
                already=c.execute('SELECT 1 FROM history WHERE source_id=? LIMIT 1',(src,)).fetchone()
                if already:
                    stats['ambiguous']+=1
                    continue
                stats['new_vessels']+=1
                if not commit:
                    # Vista previa: contabilizar eventos sin necesidad de crear el registro.
                    vid=None
                else:
                    c.execute('INSERT INTO vessels(declaration,name,captain) VALUES(?,?,?)',(dec,name,row.get('Capitán','')))
                    vid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
                    c.executemany('INSERT OR IGNORE INTO alert_settings(vessel_id,days_before) VALUES(?,?)',[(vid,30),(vid,15),(vid,1)])
            else:vid=matches[0][0]
            events=[]
            if typ=='controls':
                events.append(('ingreso',row.get('Fecha ingreso',''),row.get('Vence inicial (archivo)',''),'Registro importado; pendiente de verificación'))
                if row.get('Solicitó 9 meses') or row.get('Vence 9 meses (archivo)'):
                    events.append(('ampliacion_archivo','',row.get('Vence 9 meses (archivo)',''),'Solicitud histórica; no implica autorización'))
                for field,kind in [('Cierre o salida (texto)','salida_archivo'),('Retorno (texto)','retorno_archivo'),('Solicitud 12 meses (texto)','deposito_solicitud_archivo')]:
                    if row.get(field):events.append((kind,'','',str(row.get(field,''))[:1000]))
            else:
                events.append(('deposito_archivo',row.get('Fecha ingreso (archivo)',''),row.get('Vence depósito (archivo)',''),('Expediente: '+str(row.get('Expediente',''))+'; resolución: '+str(row.get('Resolución',''))+'; observación: '+str(row.get('Recibido / observación','')))[:1000]))
            for kind,start,expiry,description in events:
                exists=c.execute('SELECT event_date,expiry_date,description FROM history WHERE source_id=? AND kind=?',(src,kind)).fetchone()
                if exists:
                    stats['existing_events']+=1
                    if (exists[0] or '') != (start or '') or (exists[1] or '') != (expiry or ''):
                        stats['changed_records_to_review']+=1
                    continue
                stats['new_events']+=1
                if commit:
                    c.execute('INSERT OR IGNORE INTO history(vessel_id,source_id,kind,event_date,expiry_date,description) VALUES(?,?,?,?,?,?)',(vid,src,kind,start,expiry,description))
    return stats

def run_upload(c,blob,commit=False):
    data=extract_any(blob)
    return ingest(c,data,commit)
