"""Pure, side-effect-free replay of fictitious vessel movements for V62.

This module never opens a database or modifies production records.
"""
from datetime import date, timedelta
from demo_vessels import movement_transition


def replay_movements(entry_date, movements):
    """Return calculated state and history from a chronological event sequence.

    A vessel must begin in initial-entry stage; older demo records created
    directly in another stage require manual review before corrections.
    """
    if not isinstance(entry_date, date):
        raise ValueError("Fecha de ingreso inválida")
    if not isinstance(movements, (list, tuple)):
        raise ValueError("Historial inválido")
    stage = "ingreso"
    due = entry_date + timedelta(days=90)
    last_date = entry_date
    last_exit = None
    history = []
    for movement in movements:
        kind = movement["kind"]
        event_date = movement["event_date"]
        if not isinstance(event_date, date) or event_date < last_date:
            raise ValueError("Los movimientos deben conservar el orden cronológico")
        previous_stage, previous_due = stage, due
        stage, due = movement_transition(
            stage, due, entry_date, event_date, kind, last_exit
        )
        if kind == "salida":
            last_exit = {
                "event_date": event_date,
                "stage_before": previous_stage,
                "due_before": previous_due,
            }
        elif kind == "retorno":
            last_exit = None
        history.append({
            "kind": kind, "event_date": event_date,
            "stage_before": previous_stage, "due_before": previous_due,
            "stage_after": stage, "due_after": due,
        })
        last_date = event_date
    return {"stage": stage, "due_date": due, "movement_date": last_date, "history": history}
