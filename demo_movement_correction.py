"""Deterministic, testable correction plan for DEMO movement history."""
from datetime import date
from demo_movement_replay import replay_movements


def plan_movement_correction(entry_date, rows, movement_id, operation, kind=None, event_date=None,
                             current_state=None):
    """Validate and rebuild all snapshots before any database writes.

    rows: (id, kind, event_date, stage_before, due_before, stage_after, due_after).
    current_state: (stage, due_date, movement_date) from the locked vessel.
    """
    if operation not in ("edit", "delete"):
        raise ValueError("Operación inválida")
    if not rows or not any(row[0] == movement_id for row in rows):
        raise ValueError("Movimiento no encontrado")
    original = [{"kind": row[1], "event_date": row[2]} for row in rows]
    before = replay_movements(entry_date, original)
    for stored, calculated in zip(rows, before["history"]):
        if (stored[3], stored[4], stored[5], stored[6]) != (
            calculated["stage_before"], calculated["due_before"],
            calculated["stage_after"], calculated["due_after"]
        ):
            raise ValueError("Historial almacenado incompatible con el recálculo")
    if current_state is not None and (
        before["stage"], before["due_date"], before["movement_date"]
    ) != current_state:
        raise ValueError("El estado del expediente no coincide con el historial")
    if operation == "edit":
        if not isinstance(event_date, date) or not isinstance(kind, str):
            raise ValueError("Movimiento o fecha inválidos")
        if not 2000 <= event_date.year <= 2100:
            raise ValueError("Fecha fuera del rango de prueba")
    new_rows = []
    for row in rows:
        if row[0] == movement_id:
            if operation == "edit":
                new_rows.append((row[0], kind, event_date))
        else:
            new_rows.append((row[0], row[1], row[2]))
    after = replay_movements(entry_date, [
        {"kind": row[1], "event_date": row[2]} for row in new_rows
    ])
    return {"before": before, "after": after, "rows": new_rows}
