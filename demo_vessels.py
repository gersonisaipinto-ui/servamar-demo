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
