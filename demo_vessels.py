"""Separate PostgreSQL-only CRUD sandbox for fictitious SERVAMAR vessel records.

Never reads or writes the operational SQLite vessel database. No clients/emails.
"""
import calendar
import os
import re
from datetime import date, timedelta, datetime
from zoneinfo import ZoneInfo
from flask import Blueprint, jsonify, request

bp = Blueprint("demo_vessels", __name__)
URL = os.getenv("SERVAMAR_PUSH_DATABASE_URL", "").strip()
STAGES = {"ingreso", "ampliacion", "deposito", "salida", "cierre"}


def dbconnect():
    import psycopg
    return psycopg.connect(URL, connect_timeout=12)


def init_demo_vessels(app):
    # Explicit demo-only module, never connected to the operational dataset.
    if os.getenv("SERVAMAR_DEMO_MODE", "").upper() != "YES":
        raise RuntimeError("Prohibido activar CRUD de prueba fuera del modo DEMO")
    if not URL:
        raise RuntimeError("La base de prueba requiere SERVAMAR_PUSH_DATABASE_URL")
    with dbconnect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS servamar_demo_vessels (
            id BIGSERIAL PRIMARY KEY,
            registration TEXT NOT NULL UNIQUE,
            vessel_name TEXT NOT NULL,
            captain TEXT NOT NULL,
            stage TEXT NOT NULL,
            entry_date DATE NOT NULL,
            movement_date DATE NOT NULL,
            due_date DATE,
            notes TEXT NOT NULL DEFAULT '',
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
        db.execute("""CREATE TABLE IF NOT EXISTS servamar_demo_vessel_audit (
            id BIGSERIAL PRIMARY KEY,
            vessel_id BIGINT NOT NULL,
            action TEXT NOT NULL,
            registration TEXT NOT NULL,
            at_time TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
        db.execute("""CREATE TABLE IF NOT EXISTS servamar_demo_movements (
            id BIGSERIAL PRIMARY KEY,
            vessel_id BIGINT NOT NULL,
            kind TEXT NOT NULL,
            event_date DATE NOT NULL,
            stage_before TEXT NOT NULL,
            due_before DATE,
            stage_after TEXT NOT NULL,
            due_after DATE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
        db.execute("""CREATE TABLE IF NOT EXISTS servamar_demo_movement_corrections (
            id BIGSERIAL PRIMARY KEY, vessel_id BIGINT NOT NULL,
            movement_id BIGINT NOT NULL, action TEXT NOT NULL,
            registration TEXT NOT NULL, before_state JSONB NOT NULL,
            after_state JSONB NOT NULL, at_time TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
    app.register_blueprint(bp)


def add_months(d, months):
    absolute = d.year * 12 + d.month - 1 + months
    y, m0 = divmod(absolute, 12)
    return date(y, m0 + 1, min(d.day, calendar.monthrange(y, m0 + 1)[1]))


def validate(payload):
    if not isinstance(payload, dict):
        raise ValueError("Se requiere un objeto JSON")
    registration = str(payload.get("registration") or "").strip().upper()
    vessel_name = str(payload.get("vessel_name") or "").strip()
    captain = str(payload.get("captain") or "").strip()
    stage = str(payload.get("stage") or "ingreso").strip().lower()
    notes = str(payload.get("notes") or "").strip()
    if not re.fullmatch(r"DEMO-[A-Z0-9-]{2,24}", registration):
        raise ValueError("El registro debe ser ficticio y comenzar con DEMO- (ejemplo: DEMO-001)")
    if not (2 <= len(vessel_name) <= 100 and 2 <= len(captain) <= 100):
        raise ValueError("Nombre y capitán requieren entre 2 y 100 caracteres")
    if stage not in STAGES:
        raise ValueError("Etapa inválida")
    if len(notes) > 300:
        raise ValueError("Máximo 300 caracteres en observaciones")
    try:
        entry = date.fromisoformat(str(payload.get("entry_date") or ""))
        movement = date.fromisoformat(str(payload.get("movement_date") or ""))
    except ValueError:
        raise ValueError("Fechas inválidas")
    if entry.year < 2000 or entry.year > 2100 or movement.year < 2000 or movement.year > 2100:
        raise ValueError("Fechas fuera del rango 2000-2100")
    if movement < entry:
        raise ValueError("El movimiento no puede ser anterior al ingreso")
    # For this isolated demonstration, do not infer legal authorization.
    # Date computation only previews the rules previously selected by operator.
    due = {
        "ingreso": entry + timedelta(days=90),
        "ampliacion": add_months(entry, 12),
        "deposito": add_months(movement, 12),
        "salida": movement + timedelta(days=90),
        "cierre": None,
    }[stage]
    return registration, vessel_name, captain, stage, entry, movement, due, notes


def record(row):
    return {
        "id": row[0], "registration": row[1], "vessel_name": row[2],
        "captain": row[3], "stage": row[4], "entry_date": row[5].isoformat(),
        "movement_date": row[6].isoformat(),
        "due_date": row[7].isoformat() if row[7] else None,
        "notes": row[8], "version": row[9],
        "updated_at": row[10].isoformat()
    }


SELECT = """SELECT id,registration,vessel_name,captain,stage,entry_date,
    movement_date,due_date,notes,version,updated_at FROM servamar_demo_vessels"""


@bp.route("/api/demo/vessels", methods=["GET", "POST"])
def vessels():
    if request.method == "GET":
        with dbconnect() as db:
            rows = db.execute(SELECT + " ORDER BY due_date NULLS LAST, id DESC LIMIT 200").fetchall()
        return jsonify(ok=True, editable=True, persistent=True,
                       note="Laboratorio separado; no aparece en los expedientes de producción.",
                       items=[record(x) for x in rows])
    try:
        data = validate(request.get_json(silent=True))
    except ValueError as error:
        return jsonify(error=str(error)), 400
    from psycopg.errors import UniqueViolation
    try:
        with dbconnect() as db:
            count = db.execute("SELECT COUNT(*) FROM servamar_demo_vessels").fetchone()[0]
            if count >= 100:
                return jsonify(error="Máximo 100 registros ficticios de prueba"), 409
            row = db.execute("""INSERT INTO servamar_demo_vessels
                (registration,vessel_name,captain,stage,entry_date,movement_date,due_date,notes)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""", data).fetchone()
            db.execute("""INSERT INTO servamar_demo_vessel_audit(vessel_id,action,registration)
                VALUES(%s,'create',%s)""",(row[0],data[0]))
    except UniqueViolation:
        return jsonify(error="Ya existe ese número de registro de prueba"),409
    return jsonify(ok=True,id=row[0]),201


@bp.route("/api/demo/vessels/<int:vessel_id>", methods=["PATCH", "DELETE"])
def vessel_edit(vessel_id):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="Solicitud JSON inválida"),400
    try:
        expected = int(payload.get("version"))
        if expected < 1: raise ValueError()
    except (TypeError, ValueError):
        return jsonify(error="Falta la versión del registro; actualiza la lista"),400
    if request.method == "PATCH":
        try: data = validate(payload)
        except ValueError as exc: return jsonify(error=str(exc)),400
        from psycopg.errors import UniqueViolation
        try:
            with dbconnect() as db:
                current=db.execute("""SELECT stage FROM servamar_demo_vessels
                    WHERE id=%s AND version=%s FOR UPDATE""",(vessel_id,expected)).fetchone()
                if not current:
                    return jsonify(error="El registro cambió o fue eliminado; actualiza la lista"),409
                if data[3] != current[0]:
                    return jsonify(error="Para cambiar de etapa utiliza Registrar movimiento; así conservamos su historial"),400
                history_count=db.execute("""SELECT COUNT(*) FROM servamar_demo_movements
                    WHERE vessel_id=%s""",(vessel_id,)).fetchone()[0]
                if history_count:
                    existing_dates=db.execute("""SELECT entry_date,movement_date FROM servamar_demo_vessels
                        WHERE id=%s""",(vessel_id,)).fetchone()
                    if data[4] != existing_dates[0] or data[5] != existing_dates[1]:
                        return jsonify(error="Con movimientos registrados, las fechas deben corregirse desde el historial para conservar el recálculo"),400
                    current_due=db.execute("SELECT due_date FROM servamar_demo_vessels WHERE id=%s",
                                           (vessel_id,)).fetchone()[0]
                    data=(*data[:6],current_due,data[7])
                row = db.execute("""UPDATE servamar_demo_vessels SET
                    registration=%s,vessel_name=%s,captain=%s,stage=%s,entry_date=%s,
                    movement_date=%s,due_date=%s,notes=%s,version=version+1,updated_at=NOW()
                    WHERE id=%s AND version=%s RETURNING id""",(*data,vessel_id,expected)).fetchone()
                if not row:
                    return jsonify(error="El registro cambió o fue eliminado; actualiza la lista"),409
                db.execute("""INSERT INTO servamar_demo_vessel_audit(vessel_id,action,registration)
                    VALUES(%s,'update',%s)""",(vessel_id,data[0]))
        except UniqueViolation:
            return jsonify(error="Ya existe ese número de registro de prueba"),409
        return jsonify(ok=True)
    with dbconnect() as db:
        existing = db.execute("""DELETE FROM servamar_demo_vessels WHERE id=%s AND version=%s
            RETURNING registration""",(vessel_id,expected)).fetchone()
        if not existing:
            return jsonify(error="El registro cambió o fue eliminado; actualiza la lista"),409
        db.execute("""INSERT INTO servamar_demo_vessel_audit(vessel_id,action,registration)
            VALUES(%s,'delete',%s)""",(vessel_id,existing[0]))
    return jsonify(ok=True)


@bp.get("/api/demo/audit")
def audit():
    with dbconnect() as db:
        rows=db.execute("""SELECT vessel_id,action,registration,at_time
            FROM servamar_demo_vessel_audit ORDER BY id DESC LIMIT 30""").fetchall()
    return jsonify(ok=True,items=[{
        "id":r[0],"action":r[1],"registration":r[2],
        "at":r[3].astimezone(ZoneInfo("America/Guatemala")).isoformat()
    } for r in rows])


def movement_transition(stage, due, entry, event_date, kind, previous_exit=None):
    """Movimientos ficticios sin efectos sobre permisos reales.

    La fecha indicada por el usuario es una simulación: no certifica permisos.
    """
    if kind not in {"ampliacion","deposito","salida","retorno","cierre"}:
        raise ValueError("Movimiento de prueba inválido")
    if event_date < entry:
        raise ValueError("El movimiento no puede anteceder al ingreso")
    if stage == "cierre":
        raise ValueError("Un permiso cerrado no admite movimientos; crea un nuevo ingreso de prueba")
    if kind == "ampliacion":
        if stage != "ingreso":
            raise ValueError("La ampliación solo procede desde ingreso inicial en este laboratorio")
        return "ampliacion",add_months(entry,12)
    if kind == "deposito":
        if stage not in ("ingreso","ampliacion"):
            raise ValueError("No se puede ingresar a depósito desde esta etapa")
        return "deposito",add_months(event_date,12)
    if kind == "salida":
        if stage not in ("ingreso","ampliacion"):
            raise ValueError("La salida temporal no está permitida desde depósito o con otra salida abierta")
        return "salida",event_date+timedelta(days=90)
    if kind == "retorno":
        if stage != "salida" or not previous_exit:
            raise ValueError("No existe salida temporal activa para registrar el retorno")
        exit_date=previous_exit["event_date"]
        if event_date < exit_date:
            raise ValueError("El retorno no puede ser anterior a la salida")
        days_away=(event_date-exit_date).days
        if days_away>=90:
            return "cierre",None
        saved_stage=previous_exit["stage_before"]
        saved_due=previous_exit["due_before"]
        if not saved_due:
            raise ValueError("Falta el vencimiento anterior a la salida")
        return saved_stage,saved_due+timedelta(days=days_away)
    return "cierre",None


@bp.post("/api/demo/vessels/<int:vessel_id>/movement")
def add_demo_movement(vessel_id):
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict):
        return jsonify(error="Solicitud JSON inválida"),400
    try:
        expected=int(payload.get("version"))
        if expected<1:raise ValueError("Versión no válida")
        kind=str(payload.get("kind") or "").strip().lower()
        event_date=date.fromisoformat(str(payload.get("event_date") or ""))
        if not 2000<=event_date.year<=2100:raise ValueError("Fecha fuera del rango de prueba")
    except (TypeError,ValueError) as e:
        return jsonify(error=str(e) or "Verifica la fecha y la versión"),400
    with dbconnect() as db:
        v=db.execute("""SELECT registration,stage,due_date,entry_date,movement_date,version
            FROM servamar_demo_vessels WHERE id=%s FOR UPDATE""",(vessel_id,)).fetchone()
        if not v:return jsonify(error="Registro ficticio no encontrado"),404
        registration,stage,due,entry,last_date,version=v
        if version!=expected:return jsonify(error="Este registro fue editado. Actualiza la lista"),409
        if event_date<last_date:
            return jsonify(error="La fecha del movimiento no puede ser anterior al último movimiento registrado"),400
        previous_exit=None
        if kind=="retorno":
            last=db.execute("""SELECT event_date,stage_before,due_before
                FROM servamar_demo_movements WHERE vessel_id=%s AND kind='salida'
                ORDER BY id DESC LIMIT 1""",(vessel_id,)).fetchone()
            if last:
                previous_exit={"event_date":last[0],"stage_before":last[1],"due_before":last[2]}
        try:
            next_stage,next_due=movement_transition(stage,due,entry,event_date,kind,previous_exit)
        except ValueError as exc:
            return jsonify(error=str(exc)),400
        db.execute("""UPDATE servamar_demo_vessels
            SET stage=%s,due_date=%s,movement_date=%s,version=version+1,updated_at=NOW()
            WHERE id=%s""",(next_stage,next_due,event_date,vessel_id))
        db.execute("""INSERT INTO servamar_demo_movements
            (vessel_id,kind,event_date,stage_before,due_before,stage_after,due_after)
            VALUES(%s,%s,%s,%s,%s,%s,%s)""",
            (vessel_id,kind,event_date,stage,due,next_stage,next_due))
        db.execute("""INSERT INTO servamar_demo_vessel_audit(vessel_id,action,registration)
            VALUES(%s,%s,%s)""",(vessel_id,"movement_"+kind,registration))
    return jsonify(ok=True,stage=next_stage,due_date=next_due.isoformat() if next_due else None)


@bp.get("/api/demo/vessels/<int:vessel_id>/movements")
def demo_movement_history(vessel_id):
    with dbconnect() as db:
        rows=db.execute("""SELECT id,kind,event_date,stage_before,due_before,stage_after,due_after
            FROM servamar_demo_movements WHERE vessel_id=%s ORDER BY id DESC LIMIT 50""",
            (vessel_id,)).fetchall()
    return jsonify(ok=True,items=[{
        "id":r[0],"kind":r[1],"event_date":r[2].isoformat(),"stage_before":r[3],
        "due_before":r[4].isoformat() if r[4] else None,"stage_after":r[5],
        "due_after":r[6].isoformat() if r[6] else None} for r in rows])



@bp.route("/api/demo/vessels/<int:vessel_id>/movements/<int:movement_id>", methods=["PATCH", "DELETE"])
def correct_demo_movement(vessel_id, movement_id):
    """Transactional correction; reject legacy histories that cannot be replayed safely."""
    from demo_movement_correction import plan_movement_correction
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="Se requiere JSON con la versión del expediente"), 400
    try:
        expected = int(payload.get("version"))
        if expected < 1:
            raise ValueError()
        if request.method == "PATCH":
            kind = str(payload.get("kind") or "").strip().lower()
            event_date = date.fromisoformat(str(payload.get("event_date") or ""))
            if not 2000 <= event_date.year <= 2100:
                raise ValueError()
    except (ValueError, TypeError):
        return jsonify(error="Versión, tipo o fecha inválidos"), 400
    with dbconnect() as db:
        vessel = db.execute("""SELECT registration,stage,due_date,entry_date,movement_date,version
            FROM servamar_demo_vessels WHERE id=%s FOR UPDATE""", (vessel_id,)).fetchone()
        if vessel is None:
            return jsonify(error="Expediente DEMO no encontrado"), 404
        registration, stage, due, entry, last_date, version = vessel
        if version != expected:
            return jsonify(error="El expediente cambió. Actualiza la lista antes de corregir"), 409
        raw = db.execute("""SELECT id,kind,event_date,stage_before,due_before,stage_after,due_after
            FROM servamar_demo_movements WHERE vessel_id=%s ORDER BY id FOR UPDATE""",
            (vessel_id,)).fetchall()
        if not any(row[0] == movement_id for row in raw):
            return jsonify(error="Movimiento no encontrado"), 404
        # No writes occur until the complete chronology and stored snapshots pass.
        try:
            plan = plan_movement_correction(
                entry, raw, movement_id,
                "edit" if request.method == "PATCH" else "delete",
                kind if request.method == "PATCH" else None,
                event_date if request.method == "PATCH" else None,
                (stage, due, last_date))
        except (ValueError, KeyError, TypeError) as exc:
            return jsonify(error="Corrección bloqueada: " + str(exc)), 409
        after = plan["after"]
        # Preserve existing IDs and recalculate all surviving downstream snapshots.
        import json
        def snapshot(items):
            return json.dumps([{"id": item[0], "kind": item[1],
                "event_date": item[2].isoformat()} for item in items])
        new_rows = plan["rows"]
        if request.method == "DELETE":
            db.execute("DELETE FROM servamar_demo_movements WHERE id=%s AND vessel_id=%s",
                       (movement_id, vessel_id))
        for row, state in zip(new_rows, after["history"]):
            db.execute("""UPDATE servamar_demo_movements SET kind=%s,event_date=%s,
                stage_before=%s,due_before=%s,stage_after=%s,due_after=%s
                WHERE id=%s AND vessel_id=%s""",
                (state["kind"], state["event_date"], state["stage_before"],
                 state["due_before"], state["stage_after"], state["due_after"],
                 row[0], vessel_id))
        db.execute("""UPDATE servamar_demo_vessels SET stage=%s,due_date=%s,
            movement_date=%s,version=version+1,updated_at=NOW() WHERE id=%s""",
            (after["stage"], after["due_date"], after["movement_date"], vessel_id))
        db.execute("""INSERT INTO servamar_demo_movement_corrections
            (vessel_id,movement_id,action,registration,before_state,after_state)
            VALUES(%s,%s,%s,%s,%s::jsonb,%s::jsonb)""",
            (vessel_id, movement_id, "edit" if request.method == "PATCH" else "delete",
             registration, snapshot(raw), json.dumps([
                 {"id": row[0], "kind": row[1], "event_date": row[2].isoformat()}
                 for row in new_rows])))
        db.execute("""INSERT INTO servamar_demo_vessel_audit(vessel_id,action,registration)
            VALUES(%s,%s,%s)""", (vessel_id,
            "movement_correct" if request.method == "PATCH" else "movement_delete", registration))
    return jsonify(ok=True, stage=after["stage"],
                   due_date=after["due_date"].isoformat() if after["due_date"] else None,
                   version=version + 1, movements=len(new_rows))


def demo_operational_rows(today=None):
    """Read-only summary of *fictitious* PostgreSQL vessels for the demo dashboard."""
    today=today or datetime.now(ZoneInfo("America/Guatemala")).date()
    with dbconnect() as db:
        rows=db.execute("""SELECT id,registration,vessel_name,captain,stage,entry_date,
            movement_date,due_date FROM servamar_demo_vessels
            ORDER BY due_date NULLS LAST,id""").fetchall()
    summary=[]
    for id_,registration,name,captain,stage,entry,movement,deadline in rows:
        # An open exit has a 90-day return deadline, not a permit expiry.
        if stage=="cierre" or deadline is None:
            continue
        remaining=(deadline-today).days
        is_exit=stage=="salida"
        summary.append({
            "id":id_,"name":name,"captain":captain,"declaration":registration,
            "registration_number":registration,"stage":stage,
            "permit_stage":stage,"expiry_date":deadline.isoformat(),
            "remaining_days":remaining,"status":(
                "Salida temporal" if is_exit and remaining>=0 else
                "90 días fuera cumplidos" if is_exit else
                "Vencido" if remaining<0 else "Vigente"),
            "temporarily_away":is_exit,"operational_date":deadline.isoformat(),
            "operational_remaining_days":remaining,
            "closure_due_to_90_days":bool(is_exit and remaining<=0),
            "date_quality":"confirmado","candidate_count":0,
            "return_deadline":deadline.isoformat() if is_exit else None,
            "return_days_left":remaining if is_exit else None,
            "historical_departure":False,
            "days_out":max(0,(today-movement).days) if is_exit else 0,
            "demo_pg":True,"source":"PostgreSQL DEMO"
        })
    return summary


def demo_reminders_for_day(today):
    """Actual demo schedule rules, never customer contacts or operational vessel IDs."""
    from datetime import timedelta
    from app import due
    items=[]
    for row in demo_operational_rows(today):
        deadline=date.fromisoformat(row["operational_date"])
        exit_open=row["temporarily_away"]
        if exit_open and row["closure_due_to_90_days"]:
            continue
        intervals=(30,15,7,1) if exit_open else (30,15,1)
        for days in intervals:
            notify=deadline-timedelta(days=days) if exit_open else due(deadline,days)
            if notify==today:
                items.append({
                    "vessel_id":"demo-pg-"+str(row["id"]),
                    "declaration":row["declaration"],"vessel":row["name"],
                    "category":"retorno_temporal" if exit_open else "vencimiento",
                    "expiry_date":deadline.isoformat(),"days_before":days,
                    "recipients":["administracion"],"source":"PostgreSQL DEMO",
                    "demo_pg":True
                })
    return items


def demo_export_records(rows):
    """Map persisted DEMO rows into the existing SERVAMAR report columns."""
    today=datetime.now(ZoneInfo("America/Guatemala")).date()
    result=[]
    for row in rows:
        stage=row["stage"]
        due_date=date.fromisoformat(row["due_date"]) if row["due_date"] else None
        days=(due_date-today).days if due_date else None
        status=("Permiso cerrado" if stage=="cierre" else
                "Fuera de Guatemala" if stage=="salida" and days is not None and days>0 else
                "90 días fuera cumplidos" if stage=="salida" else
                "Vencido" if days is not None and days<0 else
                "Vigente" if days is not None else "Sin plazo")
        fmt=lambda v: (date.fromisoformat(v).strftime("%d/%m/%Y") if v else "")
        # Prefixing text apostrophe in XLSX/CSV inputs prevents spreadsheet
        # formula injection if untrusted text begins with =,+,-,@.
        safe=lambda v: ("'"+v if str(v or "").startswith(("=","+","-","@")) else v)
        result.append({
            "declaration":safe(row["registration"]),
            "name":safe(row["vessel_name"]),
            "registration_number":safe(row["registration"]),
            "captain":safe(row["captain"]),
            "ingress":fmt(row["entry_date"]),
            "expiry":fmt(row["due_date"]),
            "stage":stage,
            "status":status,
            "remaining":days if days is not None else "",
            "quality":"FICTICIO · PostgreSQL DEMO",
            "email":""
        })
    return result


def demo_export_filter(rows,period,field,start_raw="",end_raw=""):
    """Filter and sort only demo rows; avoids historic operational exports."""
    today=datetime.now(ZoneInfo("America/Guatemala")).date()
    if field not in ("vencimiento","ingreso"):
        raise ValueError("Campo de fecha inválido")
    if period not in ("all","month","year","previous_year","next30","last30","custom"):
        raise ValueError("Período inválido")
    start=end=None
    if period=="month":
        start=today.replace(day=1)
        end=add_months(start,1)-timedelta(days=1)
    elif period=="year":
        start,end=date(today.year,1,1),date(today.year,12,31)
    elif period=="previous_year":
        start,end=date(today.year-1,1,1),date(today.year-1,12,31)
    elif period=="next30":
        start,end=today,today+timedelta(days=30)
    elif period=="last30":
        start,end=today-timedelta(days=30),today
    elif period=="custom":
        try:
            start=date.fromisoformat(start_raw)
            end=date.fromisoformat(end_raw)
        except (TypeError,ValueError):
            raise ValueError("Ingresa ambas fechas válidas para el período personalizado")
        if start>end: raise ValueError("La fecha inicial debe ser anterior o igual a la final")
    filtered=[]
    for row in rows:
        value=row["entry_date"] if field=="ingreso" else row["due_date"]
        if start is not None and (not value or not start<=date.fromisoformat(value)<=end):
            continue
        filtered.append(row)
    return sorted(filtered,key=lambda r:(r["due_date"] is None,r["due_date"] or "9999-12-31",r["registration"]))


@bp.get("/api/demo/export/preview")
def preview_demo_control():
    """Read-only preview using the same filters as the actual DEMO export."""
    with dbconnect() as db:
        values=db.execute(SELECT+" ORDER BY due_date NULLS LAST,id LIMIT 500").fetchall()
    rows=[record(row) for row in values]
    try:
        selected=demo_export_filter(rows,request.args.get("period","all"),
                     request.args.get("field","vencimiento"),
                     request.args.get("from",""),request.args.get("to",""))
    except ValueError as exc:
        return jsonify(error=str(exc)),400
    return jsonify(ok=True,count=len(selected),items=[{
        "registration":r["registration"],
        "vessel_name":r["vessel_name"],
        "captain":r["captain"],
        "stage":r["stage"],
        "entry_date":date.fromisoformat(r["entry_date"]).strftime("%d/%m/%Y"),
        "due_date":date.fromisoformat(r["due_date"]).strftime("%d/%m/%Y") if r["due_date"] else ""
    } for r in selected[:20]],truncated=len(selected)>20,
        source="PostgreSQL DEMO",period=request.args.get("period","all"))


@bp.get("/api/demo/export")
def export_demo_control():
    """Authentically formatted Excel/PDF generated only from stored DEMO data."""
    from app import xlsx_bytes, pdf_bytes
    from flask import send_file
    import io
    fmt=request.args.get("format","xlsx").lower()
    if fmt not in ("xlsx","pdf"):
        return jsonify(error="Formato de reporte inválido"),400
    with dbconnect() as db:
        values=db.execute(SELECT+" ORDER BY due_date NULLS LAST,id LIMIT 500").fetchall()
    rows=[record(row) for row in values]
    try:
        selected=demo_export_filter(rows,request.args.get("period","all"),
                     request.args.get("field","vencimiento"),
                     request.args.get("from",""),request.args.get("to",""))
    except ValueError as e:
        return jsonify(error=str(e)),400
    data=demo_export_records(selected)
    label="SOLO DATOS FICTICIOS · PostgreSQL DEMO · "+request.args.get("period","all")
    output=xlsx_bytes(data) if fmt=="xlsx" else pdf_bytes(data,label)
    day=datetime.now(ZoneInfo("America/Guatemala")).strftime("%Y%m%d")
    return send_file(io.BytesIO(output),as_attachment=True,
        download_name=f"SERVAMAR_DEMO_Control_{day}.{fmt}",
        mimetype=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                  if fmt=="xlsx" else "application/pdf"))


def demo_backup_payload():
    """Portable JSON snapshot: demo vessel rows, movement history and audit only."""
    with dbconnect() as db:
        vessels=db.execute("""SELECT id,registration,vessel_name,captain,stage,
            entry_date,movement_date,due_date,notes,version,created_at,updated_at
            FROM servamar_demo_vessels ORDER BY id LIMIT 500""").fetchall()
        movements=db.execute("""SELECT id,vessel_id,kind,event_date,stage_before,
            due_before,stage_after,due_after,created_at
            FROM servamar_demo_movements ORDER BY id LIMIT 10000""").fetchall()
        audits=db.execute("""SELECT id,vessel_id,action,registration,at_time
            FROM servamar_demo_vessel_audit ORDER BY id LIMIT 10000""").fetchall()
    def stringify(rows,keys):
        return [dict(zip(keys,(v.isoformat() if isinstance(v,(date,datetime)) else v for v in row)))
                for row in rows]
    return {
        "format":"SERVAMAR-DEMO-BACKUP-V1",
        "created_at":datetime.now(ZoneInfo("America/Guatemala")).isoformat(),
        "scope":"Datos ficticios de PostgreSQL; NO contiene clientes, contraseñas, suscripciones push ni claves privadas",
        "vessels":stringify(vessels,("id","registration","vessel_name","captain","stage",
            "entry_date","movement_date","due_date","notes","version","created_at","updated_at")),
        "movements":stringify(movements,("id","vessel_id","kind","event_date","stage_before",
            "due_before","stage_after","due_after","created_at")),
        "audit":stringify(audits,("id","vessel_id","action","registration","at_time"))
    }


@bp.get("/api/demo/backup/status")
def demo_backup_status():
    """Read-only count check; no secret or subscription details."""
    with dbconnect() as db:
        counts={
            "vessels":db.execute("SELECT COUNT(*) FROM servamar_demo_vessels").fetchone()[0],
            "movements":db.execute("SELECT COUNT(*) FROM servamar_demo_movements").fetchone()[0],
            "audit":db.execute("SELECT COUNT(*) FROM servamar_demo_vessel_audit").fetchone()[0],
        }
    return jsonify(ok=True,counts=counts,format="SERVAMAR-DEMO-BACKUP-V1",
                   note="Solo tablas ficticias; restauración automática no disponible")


@bp.get("/api/demo/backup")
def download_demo_backup():
    """Read-only snapshot. Never serialize push credentials or operational DB."""
    from flask import send_file
    import io,json,hashlib,zipfile
    payload=demo_backup_payload()
    raw=json.dumps(payload,ensure_ascii=False,sort_keys=True,indent=2).encode("utf-8")
    metadata={
        "format":payload["format"],"created_at":payload["created_at"],
        "counts":{"vessels":len(payload["vessels"]),"movements":len(payload["movements"]),
                  "audit":len(payload["audit"])},
        "sha256_vessels_json":hashlib.sha256(raw).hexdigest(),
        "restore_note":"Respaldo descargable de prueba. La restauración automática aún no está habilitada."
    }
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,"w",compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("demo_vessels.json",raw)
        archive.writestr("manifest.json",json.dumps(metadata,ensure_ascii=False,indent=2))
    buf.seek(0)
    day=datetime.now(ZoneInfo("America/Guatemala")).strftime("%Y%m%d_%H%M")
    return send_file(buf,as_attachment=True,
                     download_name=f"SERVAMAR_DEMO_Respaldo_{day}.zip",
                     mimetype="application/zip")
