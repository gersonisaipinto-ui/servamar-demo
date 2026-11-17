"""V92: read-only search, expiry overview and CSV export for fictional vessels."""
import csv
import io
from datetime import date, timedelta
from flask import Response, jsonify, request

ALLOWED_SEARCH = ('name', 'captain', 'declaration', 'registration_number')
def register(app, protected, connection, ApiError):
    def filters():
        q = request.args.get('q', '').strip()
        month = request.args.get('month', '').strip()
        if len(q) > 120:
            raise ApiError('Búsqueda demasiado larga')
        if month:
            import re
            if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', month):
                raise ApiError('Mes inválido; utiliza yyyy-mm')
        return q, month

    def search(db, q, month):
        sql = ('SELECT id,declaration,name,captain,registration_number,stage,start_date,expiry_date '
               'FROM servamar_test.vessels WHERE declaration ~ %s')
        params = ['^ST-(DEMO|TEST)-']
        if q:
            sql += ' AND (name ILIKE %s OR captain ILIKE %s OR declaration ILIKE %s OR registration_number ILIKE %s)'
            params += ['%' + q + '%'] * 4
        if month:
            year, mon = map(int, month.split('-'))
            start = date(year, mon, 1)
            end = date(year + (mon == 12), mon % 12 + 1, 1)
            sql += ' AND expiry_date >= %s AND expiry_date < %s'
            params += [start, end]
        sql += ' ORDER BY expiry_date NULLS LAST, id LIMIT 1000'
        rows = db.execute(sql, params).fetchall()
        columns = ('id','declaration','name','captain','registration_number','stage','start_date','expiry_date')
        return [dict(zip(columns, (v.isoformat() if isinstance(v, date) else v for v in row))) for row in rows]

    @app.get('/api/test/search')
    @protected
    def search_vessels():
        q, month = filters()
        with connection() as db:
            rows = search(db, q, month)
        return jsonify(vessels=rows, count=len(rows), capped=len(rows)==1000)

    @app.get('/api/test/expiring')
    @protected
    def expiring():
        today = date.today()
        with connection() as db:
            rows = db.execute(
                "SELECT id,declaration,name,captain,expiry_date FROM servamar_test.vessels "
                "WHERE declaration ~ '^ST-(DEMO|TEST)-' AND expiry_date >= %s "
                "AND expiry_date <= %s ORDER BY expiry_date,id LIMIT 1000",
                (today, today+timedelta(days=30))).fetchall()
        return jsonify(today=today.isoformat(), vessels=[
            dict(id=r[0],declaration=r[1],name=r[2],captain=r[3],
                 expiry_date=r[4].isoformat(),days_remaining=(r[4]-today).days) for r in rows])

    @app.get('/api/test/export.csv')
    @protected
    def export_csv():
        q, month = filters()
        with connection() as db:
            rows = search(db, q, month)
        out = io.StringIO()
        writer = csv.writer(out)
        columns = ('declaration','name','captain','registration_number','stage','start_date','expiry_date')
        writer.writerow(('Matrícula ficticia','Embarcación','Capitán','Número de registro','Etapa','Ingreso','Vencimiento'))
        for row in rows:
            values = []
            for key in columns:
                value = row[key]
                if key.endswith('_date') and value:
                    value = '/'.join(reversed(value.split('-')))
                if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')):
                    value = "'" + value
                values.append(value or '')
            writer.writerow(values)
        return Response('\ufeff'+out.getvalue(),mimetype='text/csv; charset=utf-8',
                        headers={'Content-Disposition':'attachment; filename="servamar-pruebas.csv"'})
