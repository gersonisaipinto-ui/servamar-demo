"""Lector limitado, sin macros ni dependencias de Excel: solo plantilla consolidada SERVAMAR.
Las fechas importadas NUNCA validan un permiso automáticamente.
"""
import io, re, posixpath, zipfile, xml.etree.ElementTree as ET
from datetime import datetime, timedelta
MAIN='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PKG='http://schemas.openxmlformats.org/package/2006/relationships'
N={'m':MAIN,'r':REL,'p':PKG}
MAX_FILE=12*1024*1024
MAX_ROWS=15000

def normalize_date(x):
    s=str(x or '').strip()
    if not s:return ''
    for f in ('%Y-%m-%d','%d/%m/%Y','%d-%m-%Y'):
        try:return datetime.strptime(s[:10],f).date().isoformat()
        except ValueError:pass
    try:
        v=float(s)
        if 35000<v<85000:return (datetime(1899,12,30)+timedelta(days=v)).date().isoformat()
    except ValueError:pass
    return ''

def read_xlsx(blob):
    if len(blob)>MAX_FILE:raise ValueError('El archivo supera 12 MB')
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        infos=z.infolist()
        if len(infos)>300:raise ValueError('Archivo Excel demasiado complejo')
        if sum(x.file_size for x in infos)>35*1024*1024:raise ValueError('Excel descomprimido demasiado grande')
        if any('vbaProject' in x.filename or x.filename.endswith('.vba') for x in infos):raise ValueError('No se aceptan macros')
        ss=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            root=ET.fromstring(z.read('xl/sharedStrings.xml'))
            ss=[''.join(t.text or '' for t in node.findall('.//m:t',N)) for node in root.findall('m:si',N)]
        book=ET.fromstring(z.read('xl/workbook.xml'))
        rels=ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        paths={r.get('Id'):r.get('Target') for r in rels}
        sheets={}
        for s in book.findall('.//m:sheets/m:sheet',N):
            name=s.get('name');rid=s.get('{'+REL+'}id');target=paths.get(rid,'')
            if target.startswith('/'):path=target.lstrip('/')
            else:path=posixpath.normpath(posixpath.join('xl',target))
            if not path.startswith('xl/worksheets/') or path not in z.namelist():continue
            root=ET.fromstring(z.read(path));rows=[]
            for r in root.findall('.//m:sheetData/m:row',N):
                if len(rows)>=MAX_ROWS:raise ValueError('Demasiadas filas')
                vals={}
                for c in r.findall('m:c',N):
                    m=re.match(r'[A-Z]+',c.get('r',''))
                    if not m:continue
                    idx=0
                    for ch in m.group():idx=idx*26+ord(ch)-64
                    if idx>100:continue
                    v=c.find('m:v',N);inline=c.find('m:is',N)
                    value=v.text or '' if v is not None else ''
                    if c.get('t')=='s' and v is not None:
                        try:value=ss[int(value)]
                        except (ValueError,IndexError):value=''
                    elif inline is not None:value=''.join(t.text or '' for t in inline.findall('.//m:t',N))
                    vals[idx-1]=value.strip() if isinstance(value,str) else str(value)
                if vals:
                    rownum=int(r.get('r',len(rows)+1))
                    if rownum>MAX_ROWS:raise ValueError('Demasiadas filas')
                    while len(rows)<rownum-1:rows.append([])
                    rows.append([vals.get(i,'') for i in range(max(vals)+1)])
            sheets[name]=rows
        return sheets

def extract_consolidated(blob):
    sheets=read_xlsx(blob)
    spec={'CONTROL_INGRESOS':('controls',['ID origen','Declaración','Embarcación']), 'DEPOSITOS_12M':('deposits',['ID origen','Declaración','Embarcación'])}
    out={'controls':[],'deposits':[]}
    for name,(typ,need) in spec.items():
        lines=sheets.get(name,[])
        if not lines:raise ValueError('Falta la hoja '+name+' de la base unificada; primero consolida el Excel de origen')
        headers=[str(s).strip() for s in lines[0]]
        if not all(n in headers for n in need):raise ValueError('La hoja '+name+' no tiene las columnas esperadas')
        for line in lines[1:]:
            row={h:line[i].strip() if i<len(line) else '' for i,h in enumerate(headers) if h}
            if row.get('ID origen') and row.get('Declaración') and row.get('Embarcación'):
                for key in ('Fecha ingreso','Vence inicial (archivo)','Vence 9 meses (archivo)','Fecha ingreso (archivo)','Vence depósito (archivo)'):
                    if key in row:row[key]=normalize_date(row[key])
                out[typ].append(row)
    return out


def extract_any(blob):
    sheets=read_xlsx(blob)
    if 'CONTROL_INGRESOS' in sheets and 'DEPOSITOS_12M' in sheets:
        return extract_consolidated(blob)
    years=[name for name in sheets if re.fullmatch(r'20\d{2}',name)]
    if not years:raise ValueError('Excel desconocido: se requieren hojas por año o plantilla consolidada')
    # Detectar libros por columnas y contenido histórico (depósitos tienen ST en D, controles en C).
    control_count=sum(1 for year in years for row in sheets[year][1:100] if len(row)>2 and re.match(r'^(ST|PB)\s*[-–]',row[2],re.I))
    deposit_count=sum(1 for year in years for row in sheets[year][1:100] if len(row)>3 and re.match(r'^(ST|PB)\s*[-–]',row[3],re.I))
    typ='controls' if control_count>=deposit_count else 'deposits'
    if control_count==0 and deposit_count==0:raise ValueError('No se encontraron declaraciones ST/PB en las columnas esperadas')
    out={'controls':[],'deposits':[]}
    def at(row,index):return str(row[index]).strip() if len(row)>index else ''
    for year in years:
        for n,row in enumerate(sheets[year],1):
            st=at(row,2 if typ=='controls' else 3)
            name=at(row,1)
            if not re.match(r'^(ST|PB)\s*[-–]',st,re.I) or not name:continue
            if typ=='controls':
                is2026=int(year)>=2026
                out['controls'].append({
                    'ID origen':f'CONTROL/{year}/{n}', 'Año':year,'Fila Excel':str(n),
                    'Declaración':st,'Embarcación':name,'Capitán':at(row,0),
                    'Fecha ingreso':normalize_date(at(row,3)),
                    'Vence inicial (archivo)':normalize_date(at(row,4)),
                    'Solicitó 9 meses':at(row,5),'Vence 9 meses (archivo)':normalize_date(at(row,6)),
                    'Marina / registro':'' if is2026 else at(row,8),
                    'Cierre o salida (texto)':at(row,7 if is2026 else 9),
                    'Retorno (texto)':at(row,8 if is2026 else 10),
                    'Solicitud 12 meses (texto)':at(row,9 if is2026 else 11)})
            else:
                out['deposits'].append({
                    'ID origen':f'DEPOSITO/{year}/{n}','Año hoja':year,'Fila Excel':str(n),
                    'Declaración':st,'Embarcación':name,'Capitán':at(row,2),
                    'Fecha ingreso (archivo)':normalize_date(at(row,4)),
                    'Marina':at(row,5),'Documento SAT':at(row,6),
                    'Fecha presentada':normalize_date(at(row,7)),
                    'Expediente':at(row,8),'Resolución':at(row,9),
                    'Vence depósito (archivo)':normalize_date(at(row,10)),
                    'Providencia':at(row,11),'Recibido / observación':at(row,12),
                    'Pago / estado':at(row,13)})
    return out
