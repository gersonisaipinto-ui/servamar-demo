"""Private documents stored transactionally in the fictional PostgreSQL schema."""
import base64
import binascii
import hashlib
import io
import warnings
import uuid
from flask import jsonify, send_file
from werkzeug.utils import secure_filename

MAX_BYTES = 2 * 1024 * 1024
TYPES = ('permiso_ingreso','ampliacion','deposito','salida','retorno','otro')


def validate_file(data, ApiError):
    if data.get('fictional_confirmed') is not True:
        raise ApiError('Confirma que el archivo contiene exclusivamente datos ficticios')
    name = data.get('filename')
    encoded = data.get('content_base64')
    if not isinstance(name, str) or not 1 <= len(name) <= 255 or not isinstance(encoded, str):
        raise ApiError('Archivo inválido')
    name = secure_filename(name)
    if not name or len(encoded) > (MAX_BYTES + 2) // 3 * 4:
        raise ApiError('El archivo debe tener nombre y pesar como máximo 2 MB')
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ApiError('Contenido del archivo inválido')
    if not content or len(content) > MAX_BYTES:
        raise ApiError('Tamaño de archivo inválido; máximo 2 MB')
    suffix = name.rsplit('.', 1)[-1].lower()
    try:
        if suffix == 'pdf' and content.startswith(b'%PDF-'):
            import pymupdf
            with pymupdf.open(stream=content, filetype='pdf') as pdf:
                if pdf.is_encrypted or not 1 <= pdf.page_count <= 100:
                    raise ValueError('PDF unreadable')
            mime = 'application/pdf'
        elif suffix in ('jpg','jpeg','png'):
            from PIL import Image
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(content)) as picture:
                    expected = 'PNG' if suffix == 'png' else 'JPEG'
                    if picture.format != expected or picture.width * picture.height > 20000000:
                        raise ValueError('Image format or size')
                    picture.verify()
            mime = 'image/png' if suffix == 'png' else 'image/jpeg'
        else:
            raise ValueError('Unsupported file')
    except Exception:
        raise ApiError('Utiliza un PDF, JPG o PNG válido y sin contraseña')
    return name, mime, content, hashlib.sha256(content).hexdigest()


def register(app, protected, connection, get_vessel, check_version, audit, payload, text_field, ApiError):
    @app.get('/api/test/vessels/<int:vessel_id>/documents')
    @protected
    def documents(vessel_id):
        with connection() as db:
            get_vessel(db, vessel_id)
            rows = db.execute('SELECT d.id,d.document_type,d.filename,d.mime_type,d.sha256,d.uploaded_at,d.archived_at,'
                              'octet_length(c.content) FROM servamar_test.v91_documents d '
                              'LEFT JOIN servamar_test.v93_document_content c ON c.document_id=d.id '
                              'WHERE d.vessel_id=%s ORDER BY d.uploaded_at DESC,d.id DESC', (vessel_id,)).fetchall()
        keys = ('id','document_type','filename','mime_type','sha256','uploaded_at','archived_at','size_bytes')
        return jsonify(documents=[dict(zip(keys,[v.isoformat() if hasattr(v,'isoformat') else v for v in row])) for row in rows])

    @app.post('/api/test/vessels/<int:vessel_id>/documents')
    @protected
    def upload_document(vessel_id):
        data = payload()
        kind = text_field(data, 'document_type', 30)
        if kind not in TYPES:
            raise ApiError('Tipo de documento inválido')
        name, mime, content, digest = validate_file(data, ApiError)
        with connection() as db:
            vessel = get_vessel(db, vessel_id, lock=True)
            check_version(data, vessel)
            duplicate = db.execute('SELECT id FROM servamar_test.v91_documents WHERE vessel_id=%s AND sha256=%s AND archived_at IS NULL',
                                   (vessel_id,digest)).fetchone()
            if duplicate:
                raise ApiError('Este documento ya está guardado en el expediente',409)
            row = db.execute('INSERT INTO servamar_test.v91_documents '
                             '(vessel_id,document_type,filename,mime_type,sha256,storage_key,verified) '
                             'VALUES (%s,%s,%s,%s,%s,%s,true) RETURNING id',
                             (vessel_id,kind,name,mime,digest,'postgres-test/'+uuid.uuid4().hex)).fetchone()
            db.execute('INSERT INTO servamar_test.v93_document_content(document_id,content) VALUES (%s,%s)', (row[0],content))
            db.execute('UPDATE servamar_test.vessels SET version=version+1 WHERE id=%s', (vessel_id,))
            audit(db,vessel_id,'document_create',None,dict(id=row[0],filename=name,sha256=digest,size_bytes=len(content)))
            vessel = get_vessel(db,vessel_id)
        return jsonify(created=True,id=row[0],vessel=vessel),201

    @app.get('/api/test/vessels/<int:vessel_id>/documents/<int:document_id>/download')
    @protected
    def download_document(vessel_id,document_id):
        with connection() as db:
            get_vessel(db,vessel_id)
            row = db.execute('SELECT d.filename,d.mime_type,d.sha256,c.content FROM servamar_test.v91_documents d '
                             'JOIN servamar_test.v93_document_content c ON c.document_id=d.id '
                             'WHERE d.vessel_id=%s AND d.id=%s', (vessel_id,document_id)).fetchone()
        if not row:
            raise ApiError('Archivo inexistente o aún no cargado',404)
        content = bytes(row[3])
        if hashlib.sha256(content).hexdigest() != row[2]:
            raise ApiError('El archivo no supera la comprobación de integridad',409)
        return send_file(io.BytesIO(content),mimetype=row[1],as_attachment=True,download_name=row[0])

    @app.patch('/api/test/vessels/<int:vessel_id>/documents/<int:document_id>')
    @protected
    def archive_document(vessel_id,document_id):
        data=payload()
        archived=data.get('archived')
        if type(archived) is not bool:
            raise ApiError('Estado de archivo inválido')
        with connection() as db:
            vessel=get_vessel(db,vessel_id,lock=True)
            check_version(data,vessel)
            row=db.execute('SELECT archived_at,sha256 FROM servamar_test.v91_documents WHERE vessel_id=%s AND id=%s FOR UPDATE',
                           (vessel_id,document_id)).fetchone()
            if not row:
                raise ApiError('Documento inexistente',404)
            if not archived and db.execute('SELECT id FROM servamar_test.v91_documents WHERE vessel_id=%s AND sha256=%s AND id<>%s AND archived_at IS NULL',
                                           (vessel_id,row[1],document_id)).fetchone():
                raise ApiError('Ya existe una copia activa de este documento',409)
            db.execute('UPDATE servamar_test.v91_documents SET archived_at='+('now()' if archived else 'NULL')+' WHERE id=%s', (document_id,))
            db.execute('UPDATE servamar_test.vessels SET version=version+1 WHERE id=%s', (vessel_id,))
            audit(db,vessel_id,'document_archive' if archived else 'document_restore',
                  dict(id=document_id,archived=row[0] is not None),dict(id=document_id,archived=archived))
            vessel=get_vessel(db,vessel_id)
        return jsonify(updated=True,vessel=vessel)
