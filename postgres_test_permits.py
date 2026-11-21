"""Confirmed test rules: 90 days + nine calendar months; deterministic replay."""
import calendar
from datetime import date,timedelta
from postgres_test_reports import today_guatemala

RULE='90_days_plus_9_calendar_months'

class PermitError(ValueError):
    pass


def add_months(value,months):
    index=value.year*12+value.month-1+months
    year,month=divmod(index,12);month+=1
    return date(year,month,min(value.day,calendar.monthrange(year,month)[1]))


def as_date(value):
    return value if isinstance(value,date) else date.fromisoformat(value)


def calculate(entry,movements,today=None):
    today=today or today_guatemala()
    if not entry:raise PermitError('Fecha de ingreso requerida para calcular el permiso')
    entry=as_date(entry)
    if entry>today:raise PermitError('El ingreso calculado no puede estar en el futuro')
    stage='ingreso';expiry=entry+timedelta(days=90);cycle_entry=entry
    last_date=entry;departure=None;closed=None;eligible=None;reason=None;added=0;periods=[];last=None
    marker_seen=False;extension=None
    ordered=sorted(movements,key=lambda m:(as_date(m['event_date']) if m.get('event_date') else date.min,m.get('id',0)))
    for movement in ordered:
        if not movement.get('event_date'):raise PermitError('Hay un movimiento sin fecha; corrígelo antes de calcular')
        event=as_date(movement['event_date']);kind=movement['kind']
        if event<entry or event<last_date:raise PermitError('Movimiento anterior al ingreso o al historial')
        # The authorization date is a reference, separate from the extension's
        # term. Fictional future authorizations are retained and explicitly flagged.
        if event>today and kind!='ampliacion':raise PermitError('Los movimientos calculados no pueden tener fecha futura')
        last_date=event
        if kind=='ingreso':
            if not marker_seen and last is None and event==entry:
                marker_seen=True
            else:
                if departure and (event-departure['date']).days>90:
                    stage='cierre';eligible=departure['date']+timedelta(days=90)
                if stage!='cierre' or not eligible or event<eligible:
                    raise PermitError('Nuevo ingreso requiere permiso cerrado y 90 días cumplidos fuera')
                cycle_entry=event;expiry=event+timedelta(days=90);stage='ingreso';departure=None
                closed=None;eligible=None;reason=None;added=0;periods=[];marker_seen=True;extension=None
        elif kind in ('ampliacion','deposito'):
            if stage not in ('ingreso','ampliacion'):
                raise PermitError('La ampliación o el depósito requiere un permiso dentro del país, sin cierre ni salida abierta')
            if kind=='ampliacion':
                if stage!='ingreso':raise PermitError('La ampliación ya fue registrada en este permiso')
                extension=dict(base_expiry_date=expiry.isoformat(),authorization_date=event.isoformat(),
                               days_added_before_extension=added,late_days=max((event-expiry).days,0),
                               authorization_in_future=event>today)
                expiry=add_months(expiry,9);stage='ampliacion'
                extension['expiry_date']=expiry.isoformat()
            else:
                if event>expiry:raise PermitError('El depósito requiere un permiso vigente dentro del país')
                expiry=add_months(event,12);stage='deposito'
        elif kind=='salida':
            if stage not in ('ingreso','ampliacion'):
                raise PermitError('No se permite salida temporal desde depósito, cierre o una salida abierta')
            departure=dict(date=event,stage=stage,expiry=expiry,expired=event>expiry)
            eligible=event+timedelta(days=90)
            if departure['expired']:
                stage='cierre';closed=event;reason='salida_con_permiso_vencido'
            else:stage='salida'
        elif kind=='retorno':
            if not departure:raise PermitError('Retorno sin una salida registrada')
            away=(event-departure['date']).days
            if departure['expired']:
                if away<90:raise PermitError('Salida con permiso vencido: se requieren 90 días fuera antes de reingresar')
                stage='cierre';reason='salida_con_permiso_vencido'
            elif away>90:
                stage='cierre';closed=departure['date']+timedelta(days=91);reason='salida_superior_a_90_dias'
            else:
                if stage=='cierre':raise PermitError('Un retorno no puede reabrir un permiso cerrado')
                stage=departure['stage'];expiry=departure['expiry']+timedelta(days=away);added+=away
                eligible=None
            periods.append(dict(departure=departure['date'].isoformat(),returned=event.isoformat(),days_away=away,
                                days_added=away if stage!='cierre' else 0))
            # Preserve the eligibility date for a subsequent new permit, not the open departure.
            departure=None
        elif kind=='cierre':
            if stage=='cierre':raise PermitError('El permiso ya está cerrado')
            stage='cierre';closed=event;reason='cierre_registrado'
            eligible=departure['date']+timedelta(days=90) if departure else None
        else:raise PermitError('Tipo de movimiento desconocido')
        last=dict(id=movement.get('id'),kind=kind,event_date=event.isoformat())
    days_out=(today-departure['date']).days if departure else None
    if departure and stage=='salida':
        if days_out>90:
            stage='cierre';closed=departure['date']+timedelta(days=91);reason='salida_superior_a_90_dias'
    if stage=='salida':
        plazo=f'{min(days_out,90)} días fuera – cumple 90 el {eligible:%d/%m/%Y}'
    elif stage=='cierre':
        if eligible and today>=eligible:plazo=f'90 días cumplidos – se cumplieron el {eligible:%d/%m/%Y}'
        elif eligible:plazo=f'Permiso cerrado – cumple 90 días fuera el {eligible:%d/%m/%Y}'
        else:plazo=f'Permiso cerrado el {closed:%d/%m/%Y}' if closed else 'Permiso cerrado'
    else:
        days=(expiry-today).days
        plazo=f'{days} días restantes – vence el {expiry:%d/%m/%Y}' if days>=0 else f'Vencido hace {-days} días – venció el {expiry:%d/%m/%Y}'
    return dict(stage=stage,expiry_date=expiry.isoformat(),cycle_start_date=cycle_entry.isoformat(),
                days_added=added,days_out=min(days_out,90) if days_out is not None else None,
                closure_date=closed.isoformat() if closed else None,reentry_eligible_date=eligible.isoformat() if eligible else None,
                closure_reason=reason,plazo=plazo,last_movement=last,needs_review=False,periods=periods,calculation_rule=RULE,
                extension=extension)


def history_for(db,ids):
    if not ids:return {}
    rows=db.execute('SELECT vessel_id,id,kind,event_date,expiry_date FROM servamar_test.history '
                    'WHERE vessel_id=ANY(%s) ORDER BY event_date NULLS FIRST,id',(list(ids),)).fetchall()
    result={}
    for vessel_id,mid,kind,event,expiry in rows:
        result.setdefault(vessel_id,[]).append(dict(id=mid,kind=kind,event_date=event,expiry_date=expiry))
    return result


def decorate_many(db,vessels):
    calculated=[v for v in vessels if v.get('calculation_mode')=='calculated']
    histories=history_for(db,[v['id'] for v in calculated])
    today=today_guatemala()
    for vessel in vessels:
        if vessel.get('calculation_mode')=='calculated':
            try:vessel.update(calculate(vessel['start_date'],histories.get(vessel['id'],[]),today))
            except (PermitError,ValueError,OverflowError) as exc:
                vessel.update(needs_review=True,plazo='Revisión necesaria: '+str(exc))
        elif vessel.get('expiry_date'):
            expiry=as_date(vessel['expiry_date']);days=(expiry-today).days
            vessel['plazo']=(f'{days} días restantes – vence el {expiry:%d/%m/%Y}' if days>=0 else f'Vencido hace {-days} días – venció el {expiry:%d/%m/%Y}')+' · fecha manual'
        else:vessel['plazo']='Sin vencimiento manual'
    return vessels


def persist(db,vessel_id,ApiError):
    row=db.execute('SELECT start_date,calculation_mode FROM servamar_test.vessels WHERE id=%s',(vessel_id,)).fetchone()
    if row[1]!='calculated':return
    try:projection=calculate(row[0],history_for(db,[vessel_id]).get(vessel_id,[]))
    except (PermitError,ValueError,OverflowError) as exc:raise ApiError(str(exc),409)
    db.execute('UPDATE servamar_test.vessels SET stage=%s,expiry_date=%s WHERE id=%s',
               (projection['stage'],projection['expiry_date'],vessel_id))
