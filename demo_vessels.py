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
        rows=db.execute("""SELECT kind,event_date,stage_before,due_before,stage_after,due_after
            FROM servamar_demo_movements WHERE vessel_id=%s ORDER BY id DESC LIMIT 50""",
            (vessel_id,)).fetchall()
    return jsonify(ok=True,items=[{
        "kind":r[0],"event_date":r[1].isoformat(),"stage_before":r[2],
        "due_before":r[3].isoformat() if r[3] else None,"stage_after":r[4],
        "due_after":r[5].isoformat() if r[5] else None} for r in rows])


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
