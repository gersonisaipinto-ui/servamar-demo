"""Search and exports of fictional records; dates remain manually entered."""
import csv
import io
import re
import zipfile
from datetime import date, datetime, timedelta
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo
from flask import Response, jsonify, request

LIMIT = 1000
COLUMNS = ('declaration','name','captain','registration_number','stage','start_date','expiry_date')
HEADERS = ('Matrícula ficticia','Embarcación','Capitán','Número de registro','Etapa','Ingreso','Vencimiento manual')


def today_guatemala():
    return datetime.now(ZoneInfo('America/Guatemala')).date()


def safe_cell(value):
    value = '' if value is None else str(value)
    value = ''.join(c for c in value if ord(c) >= 32 or c in '\n\t')
    return "'" + value if value.lstrip().startswith(('=','+','-','@')) or value.startswith(('\t','\n')) else value


def export_rows(rows):
    result = [HEADERS]
    for row in rows:
        values=[]
        for key in COLUMNS:
            value=row[key]
            if key.endswith('_date') and value:
                value='/'.join(reversed(value.split('-')))
            values.append(safe_cell(value))
        result.append(values)
    return result


def xlsx_bytes(rows):
    """Small standards-based workbook: strings only, never spreadsheet formulas."""
    sheet=['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>']
    for number, values in enumerate(rows, 1):
        sheet.append(f'<row r="{number}">')
        for col,value in enumerate(values):
            sheet.append(f'<c r="{chr(65+col)}{number}" t="inlineStr"><is><t xml:space="preserve">{escape(str(value))}</t></is></c>')
        sheet.append('</row>')
    sheet.append('</sheetData></worksheet>')
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        archive.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        archive.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Embarcaciones ficticias" sheetId="1" r:id="rId1"/></sheets></workbook>')
        archive.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        archive.writestr('xl/worksheets/sheet1.xml',''.join(sheet))
    return output.getvalue()


def register(app, protected, connection, ApiError):
    def filters():
        q=request.args.get('q','').strip()
        month=request.args.get('month','').strip()
        field=request.args.get('date_field','expiry_date')
        stage=request.args.get('stage','')
        if len(q)>120:
            raise ApiError('Búsqueda demasiado larga')
        if field not in ('start_date','expiry_date'):
            raise ApiError('Campo de fecha inválido')
        if stage not in ('','ingreso','ampliacion','deposito','salida','cierre'):
            raise ApiError('Etapa inválida')
        if month and (not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])',month) or not 1<=int(month[:4])<=9998):
            raise ApiError('Mes inválido; utiliza yyyy-mm, años 0001 a 9998')
        def read_date(key):
            value=request.args.get(key,'').strip()
            if not value:return None
            try:
                if re.fullmatch(r'\d{2}/\d{2}/\d{4}',value):
                    return date(*map(int,reversed(value.split('/'))))
                if re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):return date.fromisoformat(value)
            except ValueError:pass
            raise ApiError('Fecha inválida; utiliza dd/mm/yyyy')
        start,end=read_date('from'),read_date('to')
        if start and end and end<start:raise ApiError('El fin del período es anterior al inicio')
        return dict(q=q,month=month,field=field,stage=stage,start=start,end=end)

    def search(db,criteria):
        sql=('SELECT id,declaration,name,captain,registration_number,stage,start_date,expiry_date '
             'FROM servamar_test.vessels WHERE declaration ~ %s')
        params=['^ST-(DEMO|TEST)-']
        q=criteria['q']
        if q:
            q=q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
            sql+=' AND (name ILIKE %s OR captain ILIKE %s OR declaration ILIKE %s OR registration_number ILIKE %s)'
            params+=['%'+q+'%']*4
        field=criteria['field'] # Whitelisted identifier only.
        if criteria['month']:
            year,mon=map(int,criteria['month'].split('-'))
            sql+=f' AND {field} >= %s AND {field} < %s'
            params += [date(year,mon,1),date(year+(mon==12),mon%12+1,1)]
        if criteria['start']:
            sql+=f' AND {field} >= %s';params.append(criteria['start'])
        if criteria['end']:
            sql+=f' AND {field} <= %s';params.append(criteria['end'])
        if criteria['stage']:
            sql+=' AND stage=%s';params.append(criteria['stage'])
        sql+=' ORDER BY expiry_date NULLS LAST,id LIMIT 1001'
        rows=db.execute(sql,params).fetchall()
        columns=('id',)+COLUMNS
        return [dict(zip(columns,(v.isoformat() if isinstance(v,date) else v for v in row))) for row in rows]

    @app.get('/api/test/search')
    @protected
    def search_vessels():
        criteria=filters()
        with connection() as db:rows=search(db,criteria)
        return jsonify(vessels=rows[:LIMIT],count=min(len(rows),LIMIT),capped=len(rows)>LIMIT)

    @app.get('/api/test/expiring')
    @protected
    def expiring():
        today=today_guatemala()
        with connection() as db:
            rows=db.execute("SELECT id,declaration,name,captain,expiry_date FROM servamar_test.vessels "
                            "WHERE declaration ~ '^ST-(DEMO|TEST)-' AND stage IN ('ingreso','ampliacion','deposito') "
                            "AND expiry_date >= %s AND expiry_date <= %s ORDER BY expiry_date,id LIMIT 1001",
                            (today,today+timedelta(days=30))).fetchall()
        return jsonify(today=today.isoformat(),manual_dates=True,capped=len(rows)>LIMIT,vessels=[
            dict(id=r[0],declaration=r[1],name=r[2],captain=r[3],expiry_date=r[4].isoformat(),days_remaining=(r[4]-today).days)
            for r in rows[:LIMIT]])

    def export_data():
        criteria=filters()
        with connection() as db:rows=search(db,criteria)
        if len(rows)>LIMIT:raise ApiError('Más de 1000 resultados: reduce el período para exportar sin omisiones',409)
        return export_rows(rows)

    @app.get('/api/test/export.csv')
    @protected
    def export_csv():
        output=io.StringIO();csv.writer(output).writerows(export_data())
        return Response('\ufeff'+output.getvalue(),mimetype='text/csv; charset=utf-8',
                        headers={'Content-Disposition':'attachment; filename="servamar-pruebas.csv"'})

    @app.get('/api/test/export.xlsx')
    @protected
    def export_xlsx():
        return Response(xlsx_bytes(export_data()),mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition':'attachment; filename="servamar-pruebas.xlsx"'})

    @app.get('/api/test/export.pdf')
    @protected
    def export_pdf():
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4,landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle
        rows=export_data();output=io.BytesIO();styles=getSampleStyleSheet()
        style=styles['BodyText'];style.fontSize=8;style.leading=10
        table=Table([[Paragraph(escape(str(value)),style) for value in row] for row in rows],
                    colWidths=[105,135,125,90,70,85,115],repeatRows=1)
        table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#d8eaed')),
                                   ('VALIGN',(0,0),(-1,-1),'TOP'),('GRID',(0,0),(-1,-1),.3,colors.HexColor('#b7cbd3')),
                                   ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
        document=SimpleDocTemplate(output,pagesize=landscape(A4),leftMargin=20,rightMargin=20,topMargin=24,bottomMargin=24)
        def footer(canvas,doc):
            canvas.setFont('Helvetica',8);canvas.drawString(20,12,'SERVAMAR · DATOS FICTICIOS · Página '+str(doc.page))
        document.build([Paragraph('SERVAMAR · Reporte de pruebas',styles['Title']),
                        Paragraph(f'{len(rows)-1} registros. Fechas manuales; cálculos automáticos pendientes de confirmación. Generado {today_guatemala():%d/%m/%Y}.',style),Spacer(1,12),table],onFirstPage=footer,onLaterPages=footer)
        return Response(output.getvalue(),mimetype='application/pdf',headers={'Content-Disposition':'attachment; filename="servamar-pruebas.pdf"'})
