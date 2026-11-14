
// V34: Identidad cromática por bloque sin modificar la lógica de los expedientes.
function decorateVesselDetail(){
 const root=$('detail');
 const groups=[
  [/^Corregir datos/i,'vessel-info'],
  [/^Datos del cliente/i,'vessel-contact'],
  [/^Registrar movimiento/i,'vessel-movement']
 ];
 for(const heading of Array.from(root.children).filter(el=>el.tagName==='H3')){
  const match=groups.find(([re])=>re.test(heading.textContent.trim()));
  if(!match)continue;
  const wrapper=document.createElement('section');
  wrapper.className='vessel-section '+match[1];
  heading.before(wrapper);
  let current=heading;
  while(current){
   if(current!==heading && current.tagName==='H3')break;
   if(current!==heading && current.tagName==='DETAILS' && /Historial de movimientos|Registro de avisos|Historial de correcciones/i.test(current.querySelector('summary')?.textContent||''))break;
   const next=current.nextElementSibling;
   wrapper.appendChild(current);
   current=next;
  }
 }
 for(const fold of root.querySelectorAll('details.detail-fold')){
  const label=fold.querySelector('summary')?.textContent||'';
  if(/Salidas temporales/i.test(label))fold.classList.add('fold-departures');
  else if(/Documentos adjuntos/i.test(label))fold.classList.add('fold-documents');
  else if(/Historial de movimientos/i.test(label))fold.classList.add('fold-history');
  else if(/Registro de avisos/i.test(label))fold.classList.add('fold-alerts');
  else if(/Historial de correcciones/i.test(label))fold.classList.add('fold-edits');
 }
 // La barra superior y el aviso tienen fondos propios; los botones usan colores según función.
 root.querySelector(':scope > .toolbar')?.classList.add('vessel-title-bar');
 root.querySelector(':scope > .actions')?.classList.add('vessel-quick-actions');
 root.querySelector(':scope > .alert')?.classList.add('vessel-expiry-banner');
}

const $=id=>document.getElementById(id);const escapeHtml=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const api=async(url,opts)=>{const r=await fetch(url,opts);const txt=await r.text();let j;try{j=JSON.parse(txt)}catch{throw Error('El servidor devolvió una página inesperada. Comprueba que está abierta la versión actual de SERVAMAR y revisa la terminal.')};if(!r.ok)throw Error(j.error||'Error de servidor ('+r.status+')');return j};const post=(url,data)=>api(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const pretty=x=>x||'—';const formatDate=x=>{if(!x)return '—';const m=String(x).match(/^(\d{4})-(\d{2})-(\d{2})(?:$|T| )/);return m?`${m[3]}/${m[2]}/${m[1]}`:String(x)};const toIsoDate = (raw, label, optional=false) => {
 const value=String(raw||'').trim();
 if(!value && optional)return '';
 const m=/^(\d{2})\/(\d{2})\/(\d{4})$/.exec(value);
 if(!m)throw Error(label+': utiliza dd/mm/yyyy (por ejemplo 05/11/2026).');
 const d=Number(m[1]),mo=Number(m[2]),y=Number(m[3]);
 const check=new Date(Date.UTC(y,mo-1,d));
 if(y<1900||y>2200||check.getUTCFullYear()!==y||check.getUTCMonth()!==mo-1||check.getUTCDate()!==d)throw Error(label+': fecha inválida.');
 return `${m[3]}-${m[2]}-${m[1]}`;
};let selected=null;let previousTab='buscar';let movementRows=[];
function showTab(tab){
 const names=['inicio','nuevo','buscar','avisos','exportar','excel'];if(document.getElementById('tab-bdpruebas'))names.push('bdpruebas');if(!names.includes(tab))tab='inicio';
 for(const name of names){const pane=$('tab-'+name);pane.hidden=name!==tab;const button=document.querySelector('[data-tab="'+name+'"]');button.classList.toggle('active',name===tab);button.setAttribute('aria-current',name===tab?'page':'false')}
 $('detail').hidden=true;previousTab=tab;
 if(tab==='inicio')loadExpirations();
 window.scrollTo({top:0,behavior:'instant'});
}
function showDetailPanel(){for(const name of ['inicio','nuevo','buscar','avisos','exportar','excel','bdpruebas']){const pane=$('tab-'+name);const tabbtn=document.querySelector('[data-tab="'+name+'"]');if(pane&&tabbtn){pane.hidden=true;tabbtn.classList.remove('active')}} $('detail').hidden=false}

async function dashboard(){const v=await api('/api/dashboard');const stats=[['Por vencer (30 días)',v.soon],['Vencidos (hist. incluidos)',v.expired],['Referencias históricas',v.review]];if(document.getElementById('tab-bdpruebas'))stats.push(['Registros persistentes DEMO',v.demo_pg_count||0]);$('stats').innerHTML=stats.map(([k,n])=>`<div class="stat"><span>${k}</span><b>${n.toLocaleString('es-GT')}</b></div>`).join('')}

// V64: preserve semantic tables on desktop; label cells for mobile cards.
function labelMobileTableRows(tbodyId, labels){
 const body=$(tbodyId);if(!body)return;
 const table=body.closest('table');if(table)table.classList.add('servamar-mobile-cards');
 for(const row of body.rows){
  if(row.cells.length!==labels.length)continue; // Empty-state rows with colspan stay readable.
  for(let i=0;i<labels.length;i++)row.cells[i].setAttribute('data-label',labels[i]);
 }
}

let lastSearchRequest=0;
function clearSearch(){for(const id of ['search','vessel-name-search','registration-search','captainsearch','entrydate','entrymonth','expirydate','expirymonth'])$(id).value='';search()}
// V39: Fila resumida con etapa, movimiento más reciente y plazo.
function compactStage(v){return v.display_stage||'Sin etapa'}
function compactTerm(v){
 const stage=compactStage(v);
 if(v.archived_closure_date)return 'Cierre registrado: '+formatDate(v.archived_closure_date);
 if(stage==='Salida Temporal'||stage==='Permiso Cerrado'){
  if(v.days_out===null||v.days_out===undefined||!v.return_deadline)
   return stage==='Permiso Cerrado'?'Permiso cerrado · sin fecha de salida':'Días fuera: sin dato · 90 días: sin fecha';
  const days=Number(v.days_out);
  // Al alcanzar 90 días o cerrar el permiso, detener el contador visible.
  if(days>=90)return '90 días cumplidos: '+formatDate(v.return_deadline);
  if(stage==='Permiso Cerrado')return 'Permiso cerrado · Límite de 90 días: '+formatDate(v.return_deadline);
  return days+' días fuera · 90 días: '+formatDate(v.return_deadline);
 }
 const exp=formatDate(v.current_expiry_date);
 if(!v.current_expiry_date)return 'Plazo sin fecha';
 if(v.remaining_days===null||v.remaining_days===undefined)return 'Vence: '+exp;
 const days=Number(v.remaining_days);
 return days<0?Math.abs(days)+' días vencido · '+exp:
        days===0?'Vence hoy · '+exp:
        days+' días restantes · '+exp;
}
async function search(){
 const requestNumber=++lastSearchRequest;
 const q=$('search').value.trim(),vessel_name=$('vessel-name-search').value.trim(),registration_number=$('registration-search').value.trim(),captain=$('captainsearch').value.trim();
 const entryDate=$('entrydate').value.trim(),entryMonth=$('entrymonth').value;
 const expiryDate=$('expirydate').value.trim(),expiryMonth=$('expirymonth').value;
 const root=$('resultmeta');
 if(!q&&!vessel_name&&!registration_number&&!captain&&!entryDate&&!entryMonth&&!expiryDate&&!expiryMonth){root.textContent='Introduce un criterio para buscar en el historial completo.';$('results').innerHTML='';return}
 if((entryDate&&entryMonth)||(expiryDate&&expiryMonth)){root.textContent='Elige una fecha exacta o un mes para cada tipo de fecha, no ambos.';$('results').innerHTML='';return}
 let entryIso='',expiryIso='';
 try{if(entryDate)entryIso=toIsoDate(entryDate,'Ingreso');if(expiryDate)expiryIso=toIsoDate(expiryDate,'Vencimiento')}
 catch(e){root.textContent=e.message;$('results').innerHTML='';return}
 const params=new URLSearchParams({limit:'120'});
 for(const [key,value] of Object.entries({q,vessel_name,registration_number,captain,entry_date:entryIso,entry_month:entryMonth,expiry_date:expiryIso,expiry_month:expiryMonth}))if(value)params.set(key,value);
 try{
  const result=await api('/api/vessels?'+params.toString());if(requestNumber!==lastSearchRequest)return;
  let demo=[];
  if(document.getElementById('tab-bdpruebas')&&typeof servamarDemoSearch==='function'){
    demo=await servamarDemoSearch({q,vessel_name,registration_number,captain,
      entry_date:entryIso,entry_month:entryMonth,expiry_date:expiryIso,expiry_month:expiryMonth});
    if(requestNumber!==lastSearchRequest)return;
  }
  root.textContent=demo.length?`${result.total} expediente(s) de muestra; ${demo.length} registro(s) editables en PostgreSQL.`:
    `${result.total} expediente(s) de muestra; sin coincidencias editables en PostgreSQL.`;
  const original=result.items.map(v=>`<tr><td>${escapeHtml(v.name)}</td><td>${escapeHtml(v.declaration)}</td><td>${escapeHtml(v.registration_number||'—')}</td><td>${escapeHtml(v.captain)}</td><td>${escapeHtml(compactStage(v))}</td><td>${escapeHtml(formatDate(v.last_movement_date))}</td><td>${escapeHtml(compactTerm(v))}</td><td><button class="secondary" onclick="openVessel(${v.id})">Abrir (solo lectura)</button></td></tr>`).join('');
  const demoRows=demo.map(v=>`<tr><td>${escapeHtml(v.vessel_name)} (DEMO)</td><td>${escapeHtml(v.registration)}</td><td>Prueba PostgreSQL</td><td>${escapeHtml(v.captain)}</td><td>${escapeHtml(v.stage)}</td><td>${escapeHtml(formatDate(v.movement_date))}</td><td>${escapeHtml(formatDate(v.due_date))}</td><td><button class="secondary" onclick="servamarDemoEditById(${v.id})">Editar en prueba</button></td></tr>`).join('');
  $('results').innerHTML=original+demoRows||'<tr><td colspan="8">No se encontraron embarcaciones con estos filtros.</td></tr>';
  labelMobileTableRows('results',['Embarcación','Declaración','Registro','Capitán','Etapa','Último movimiento','Plazo','Acciones']);
 }catch(e){if(requestNumber===lastSearchRequest){root.textContent=e.message;$('results').innerHTML=''}}
}
function renderStatusBanner(v,cd,archivedClosure){
 if(archivedClosure)return '<div class="alert"><b>Permiso cerrado — cierre histórico registrado: '+escapeHtml(formatDate(archivedClosure))+'</b></div>';
 if(cd?.closure_due_to_90_days){return '<div class="alert"><b>'+escapeHtml(cd.status)+'</b> · Límite de retorno: '+escapeHtml(formatDate(cd.return_deadline))+' · '+escapeHtml(cd.days_out)+' días fuera.</div>'}
 if(v.stage==='cierre'){
  const reason=v.closure_reason==='salida temporal sin retorno'?'90 días fuera cumplidos':'cierre registrado';
  return '<div class="alert"><b>Permiso cerrado — '+reason+'</b>'+(v.closure_date?' · Fecha del cierre: '+escapeHtml(formatDate(v.closure_date)):'')+'</div>';
 }
 const msg=v.stage==='revision'?'Referencia histórica aceptada para consulta.':v.validated?'Etapa registrada en la ficha':'Datos históricos importados.';
 return '<div class="alert">'+msg+' · Vencimiento '+(cd&&cd.date_quality!=='confirmado'?'histórico de referencia':'registrado')+': <b>'+escapeHtml(formatDate(cd?cd.expiry_date:v.expiry_date))+'</b>'+(cd?' · '+escapeHtml(cd.stage)+' · '+escapeHtml(cd.status)+' · '+(cd.remaining_days<0?Math.abs(cd.remaining_days)+' días vencidos':cd.remaining_days+' días restantes'):'')+'</div>';
}
async function openVessel(id){selected=id;const j=await api('/api/vessels/'+id);const v=j.vessel;const h=j.history;movementRows=h;const cd=j.current_deadline;const te=j.temporary_exit||{};showDetailPanel();$('detail').innerHTML=`<div class="toolbar"><div><h2>${escapeHtml(v.name)}</h2><p>${escapeHtml(v.declaration)} · Registro: ${escapeHtml(v.registration_number||"No consignado")} · Capitán: ${escapeHtml(v.captain)}</p></div><button class="secondary" onclick="showTab(previousTab)">Volver</button></div><div class="actions" style="margin:12px 0"><button type="button" onclick="previewManualClientEmail()">✉ Vista previa del correo</button><button type="button" class="secondary" onclick="document.getElementById('email').scrollIntoView({behavior:'smooth',block:'center'});document.getElementById('email').focus()">Editar correo</button><button type="button" class="secondary" onclick="document.getElementById('movement-form').scrollIntoView({behavior:'smooth',block:'center'});document.getElementById('kind').focus()">+ Registrar movimiento</button></div><p id="manual-email-message" class="muted">Guarda la dirección y el consentimiento del cliente. Después revisa el correo antes de enviarlo.</p><div id="manual-email-preview" class="mail-preview" hidden></div>${!v.validated && cd && cd.expiry_date && !cd.closure_due_to_90_days?'<div class="actions" style="margin:10px 0"><button type="button" class="secondary" onclick="confirmHistoricalExpiry()">Confirmar fecha de vencimiento del expediente</button></div>':''}${renderStatusBanner(v,cd,j.archived_closure_date)}<details class="detail-fold" open><summary>Salidas temporales · ${cd?.closure_due_to_90_days?'Permiso cerrado — 90 días fuera cumplidos':te.currently_away?(te.return_days_left<0?'Plazo excedido: '+Math.abs(te.return_days_left)+' días':te.return_days_left+' días hasta el límite'):'Sin salida activa'}</summary><p><b>${te.currently_away?te.current_days_away+' días fuera desde '+formatDate(te.current_departure):'Total acumulado: '+(te.total_days_away||0)+' días fuera · '+(te.days_added||0)+' días añadidos al vencimiento'}</b></p><p class="muted">${escapeHtml(te.note||'Los retornos oportunos amplían el vencimiento.')}</p>${te.historical_departure?'<p class="muted"><b>Fecha recuperada del Excel:</b> comprobar si hubo retorno o cierre antes de actualizar el permiso.</p>':''}${te.currently_away&&!cd?.closure_due_to_90_days?'<p><b>Retornar antes del '+formatDate(te.return_deadline)+'</b> · A los 90 días fuera se cierra el permiso. Los datos importados sin retorno necesitan conciliación.</p>':''}${v.stage==='cierre'?'<p><b>Permiso cerrado — '+(v.closure_reason==='salida temporal sin retorno'?'90 días fuera cumplidos.':'cierre registrado.')+'</b> Reingreso posible desde: '+formatDate(j.reentry_eligible_date)+'</p>':''}<ul class="history">${(te.periods||[]).map(t=>`<li>Salida ${formatDate(t.departure)} · ${t.return?'Retorno '+formatDate(t.return):'Sin retorno registrado'} · ${t.days_away} días fuera</li>`).join('')||'<li>No hay salidas temporales registradas.</li>'}</ul>${(te.warnings||[]).map(x=>`<p class="muted">${escapeHtml(x)}</p>`).join('')}</details><h3>Corregir datos de la embarcación</h3><div class="grid"><label class="field">Nombre de embarcación<input id="vesselname" name="nombre_embarcacion_editar" autocomplete="off" value="${escapeHtml(v.name)}" maxlength="200"></label><label class="field">Declaración ST<input id="declaration" name="declaracion_st_editar" autocomplete="off" value="${escapeHtml(v.declaration)}" maxlength="200"></label><label class="field">Número de registro (opcional)<input id="registration-number" name="registro_embarcacion_editar" autocomplete="off" value="${escapeHtml(v.registration_number||'')}" maxlength="200" placeholder="Identificador de la embarcación"></label><label class="field">Capitán<input id="captain" name="capitan_embarcacion_editar" autocomplete="off" value="${escapeHtml(v.captain)}" maxlength="200"></label></div><p class="muted">Las correcciones conservan el historial y se registran para auditoría. Verifica la declaración antes de guardarla.</p><div class="linked-permits"><h3>Otros permisos con el mismo registro</h3>${j.related_registration.length?`<ul class="history">${j.related_registration.map(x=>`<li><button type="button" class="secondary" onclick="openVessel(${x.id})">${escapeHtml(x.declaration)} · ${escapeHtml(x.name)}</button></li>`).join('')}</ul>`:'<p class="muted">Sin otros permisos vinculados por número de registro.</p>'}</div><h3>Datos del cliente y recordatorios</h3><div class="grid"><label class="field">Correo del cliente<input id="email" type="email" name="correo_cliente_servamar" autocomplete="email" value="${escapeHtml(v.email)}" placeholder="cliente@correo.com"></label><label class="field">Avisos antes del vencimiento (días separados por coma; 30 = un mes calendario)<input id="days" value="${j.days.join(', ')}"></label><label class="check"><input id="optin" type="checkbox" ${v.client_opt_in?'checked':''}>Cliente autorizó recibir avisos</label><label class="check"><input id="clientapproved" type="checkbox" ${v.client_send_approved?'checked':''}>Aprobé el envío automático para este expediente (requiere activar servidor)</label><label class="field full">Notas internas<textarea id="notes" rows="2">${escapeHtml(v.notes)}</textarea></label></div><div class="actions"><button onclick="saveDetails()">Guardar ficha y correo</button><button type="button" class="secondary" onclick="previewManualClientEmail()">Vista previa sin enviar</button></div><details class="detail-fold"><summary>Documentos adjuntos al expediente</summary><div class="actions"><input type="file" id="attach-permit" accept="image/jpeg,image/png,image/webp,application/pdf"><button class="secondary" onclick="attachPermit(${v.id})">Guardar documento</button></div><p id="doc-status" class="muted"></p><ul class="history" id="documents-list"></ul></details><h3 id="movement-form">Registrar movimiento</h3><div class="grid"><label class="field">Movimiento<select id="kind"><option value="ingreso">Nuevo ingreso (90 días)</option><option value="ampliacion">Ampliación (9 meses)</option><option value="deposito">Depósito (12 meses)</option><option value="salida">Salida temporal</option><option value="retorno">Retorno de salida temporal</option><option value="cierre">Cierre</option></select></label><label class="field">Fecha del movimiento<input id="start" type="text" inputmode="numeric" placeholder="dd/mm/yyyy" maxlength="10" autocomplete="off"></label><label class="field">Vencimiento calculado<input id="expiry" type="text" readonly placeholder="Se calculará automáticamente"></label><label class="field full">Documento / resolución / observaciones<input id="description" placeholder="Número de resolución y referencia"></label></div><p class="muted">Ingreso: +90 días. Ampliación: un año calendario desde el ingreso inicial; fecha de autorización opcional (recomendado consignarla para trazabilidad). Depósito: +12 meses calendario desde su fecha efectiva de ingreso. Salida temporal: máximo 90 días fuera; si retorna antes, los días fuera se suman al vencimiento. Al día 90 sin retorno: cierre automático. Depósito: sin salidas temporales. Cierre definitivo: reingreso desde 90 días después. Las solicitudes históricas no se consideran autorizaciones.</p><div class="actions"><button onclick="saveEvent()">Registrar movimiento</button></div><p id="message"></p><details class="detail-fold"><summary>Historial de movimientos (${h.length})</summary><div id="movement-edit-panel"></div><ul class="history">${h.map((r,i)=>`<li><b>${escapeHtml(r.kind)}</b> · ${escapeHtml(formatDate(r.event_date))} → ${escapeHtml(formatDate(r.expiry_date))}<br><span class="muted">${escapeHtml(r.description)}</span><div class="actions" style="margin-top:8px"><button type="button" class="secondary" onclick="editMovement(${r.id})">Modificar movimiento</button></div>${i===0 && r.source_id==null && ['ingreso','ampliacion','deposito','salida','retorno','cierre'].includes(r.kind)?`<div class="actions" style="margin-top:8px"><button type="button" class="secondary" onclick="deleteMovement(${r.id})">Eliminar movimiento</button></div>`:''}</li>`).join('')}</ul></details><details class="detail-fold"><summary>Registro de avisos</summary><ul class="history">${j.logs.length?j.logs.map(r=>`<li>${escapeHtml(formatDate(r.sent_at))} · ${escapeHtml(r.destination)} · ${escapeHtml(r.status)} · ${escapeHtml(r.detail)}</li>`).join(''):'<li>Todavía no se han enviado avisos.</li>'}</ul></details>`;decorateVesselDetail();bindMovementPreview();loadEdits(id);loadPermitDocuments(id);$('detail').scrollIntoView({behavior:'smooth',block:'start'})}
async function confirmHistoricalExpiry(){
 const msg=$('manual-email-message');
 try{
  const j=await api('/api/vessels/'+selected);const date=j.current_deadline?.expiry_date;
  if(!date)throw Error('No existe fecha de vencimiento disponible para confirmar.');
  if(!confirm('¿Confirmas que la fecha vigente del permiso '+j.vessel.declaration+' es '+formatDate(date)+'? Esta acción no envía correos ni exige adjuntar documentos.'))return;
  const result=await post('/api/vessels/'+selected+'/confirm-current-deadline',{confirmation:'CONFIRMAR',expiry_date:date});
  await Promise.all([dashboard(),search(),loadExpirations()]);await openVessel(selected);
  $('manual-email-message').textContent=result.message;
 }catch(e){msg.textContent=e.message}
}
async function saveDetails(){const days=$('days').value.split(',').map(x=>Number(x.trim())).filter(Number.isFinite);try{await post('/api/vessels/'+selected,{name:$('vesselname').value,declaration:$('declaration').value,registration_number:$('registration-number').value,captain:$('captain').value,email:$('email').value,client_opt_in:$('optin').checked,client_send_approved:$('clientapproved').checked,days,notes:$('notes').value});$('message').className='alert success';$('message').textContent='Correcciones y recordatorios guardados. No se han enviado correos.';await Promise.all([dashboard(),search(),loadExpirations()]);await openVessel(selected);$('message').className='alert success';$('message').textContent='Ficha y correo guardados. Aún no se envió ningún mensaje.'; const m=$('manual-email-message');if(m)m.textContent='Dirección y preferencias guardadas. Pulsa Vista previa del correo para revisarlo.'}catch(e){$('message').className='alert error';$('message').textContent=e.message}}
let previewSeq=0;
function bindMovementPreview(){
 $('kind').addEventListener('change',refreshMovementPreview);
 $('start').addEventListener('input',refreshMovementPreview);
 refreshMovementPreview();
}
async function refreshMovementPreview(){
 const seq=++previewSeq,kind=$('kind').value;
 const label=$('start').closest('label');
 label.firstChild.textContent=kind==='deposito'?'Fecha efectiva de ingreso a depósito':kind==='ampliacion'?'Fecha de autorización (opcional)':'Fecha del movimiento';
 $('expiry').value='';
 if(!['ingreso','ampliacion','deposito','salida','retorno','cierre'].includes(kind)){$('expiry').placeholder='No aplica';return}
 const raw=$('start').value.trim();if(!raw&&kind!=='ampliacion'){$('expiry').placeholder='Completa la fecha';return}
 try{
  const start=toIsoDate(raw,'Fecha del movimiento',kind==='ampliacion');
  const j=await api('/api/vessels/'+selected+'/movement-preview?kind='+encodeURIComponent(kind)+'&start_date='+encodeURIComponent(start));
  if(seq!==previewSeq)return;
  $('expiry').value=formatDate(j.expiry_date);$('expiry').title=j.basis;
 }catch(e){if(seq===previewSeq){$('expiry').placeholder=e.message;$('expiry').title=e.message}}
}
async function saveEvent(){
 try{
  const data={kind:$('kind').value,start_date:toIsoDate($('start').value,'Fecha del movimiento',$('kind').value==='ampliacion'),description:$('description').value};
  const result=await post('/api/vessels/'+selected+'/event',data);
  await Promise.all([dashboard(),search(),loadExpirations()]);await openVessel(selected);
  $('message').className='alert success';$('message').textContent='Movimiento registrado. '+(result.expiry_date?'Nuevo vencimiento: '+formatDate(result.expiry_date)+'. ':'')+result.basis;
 }catch(e){$('message').className='alert error';$('message').textContent=e.message}
}
let debounce;for(const id of ['search','vessel-name-search','registration-search','captainsearch','entrydate','entrymonth','expirydate','expirymonth'])$(id).addEventListener('input',()=>{clearTimeout(debounce);debounce=setTimeout(search,350)});dashboard();search();

async function loadExpirations(){try{
 const mode=$('expiry-mode').value;
 const result=await api('/api/expirations?mode='+encodeURIComponent(mode));
 $('exp-csv').href='/api/expirations.csv?mode='+encodeURIComponent(mode);
 $('expmeta').textContent=`${result.total} registros ${mode==='overdue'?'vencidos':mode==='review'?'por verificar':mode==='departures'?'con salida temporal registrada':'con vencimiento dentro de los próximos 30 días'}${result.truncated?'; se muestran los primeros 200':''}. Las referencias históricas no generan correos automáticos. ${document.getElementById('tab-bdpruebas')?'Los registros de PostgreSQL son ficticios y están identificados como DEMO. La descarga CSV tradicional aún no los incluye.':''}`;
 $('expresults').innerHTML=result.items.map(v=>{
  const stage=({'ingreso':'Ingreso 3 meses','ampliacion':'Ampliación 9 meses','deposito':'Depósito 12 meses','cierre':'Permiso Cerrado','salida':'Salida Temporal'})[v.stage]||v.stage||'Sin etapa';
  const departure=Boolean(v.temporarily_away);
  let daysText='';let importantDate=v.operational_date||(departure?v.return_deadline:v.expiry_date);
  if(departure){
    daysText=v.return_days_left<=0?'90 días cumplidos':`${Math.max(0,90-Number(v.days_out||0))} días para cumplir 90`;
  }else{
    const d=Number(v.operational_remaining_days??v.remaining_days);
    daysText=d<0?`${Math.abs(d)} días vencidos`:d===0?'Vence hoy':`${d} días restantes`;
  }
  return `<tr><td>${escapeHtml(v.name)}${v.demo_pg?' (DEMO PostgreSQL)':''}</td><td>${escapeHtml(v.captain||"—")}</td><td>${escapeHtml(stage)}</td><td>${escapeHtml(daysText)}</td><td>${escapeHtml(formatDate(importantDate))}</td><td><button class="secondary" onclick="${v.demo_pg?'servamarDemoEditById':'openVessel'}(${v.id})">${v.demo_pg?'Editar prueba':'Abrir'}</button></td></tr>`;
 }).join('')||'<tr><td colspan="6" class="empty-state">No hay embarcaciones registradas en este filtro. Puedes crear una en «Nuevo ingreso» o importar tu Excel.</td></tr>';
 labelMobileTableRows('expresults',['Embarcación','Capitán','Etapa','Plazo','Fecha','Acciones']);
 }catch(e){$('expmeta').textContent=e.message}}
async function previewAlerts(){try{if(document.getElementById('tab-bdpruebas')){const j=await api('/api/push/schedule?days=1');const today=j.start;const items=j.events.filter(e=>e.notify_on===today);$('preview').textContent=`Hoy: ${items.length} recordatorio(s), incluyendo PostgreSQL DEMO. ${items.map(x=>x.vessel+' ('+x.days_before+' días)').join('; ')||'Ninguno'}. Vista previa sin envíos a clientes.`;return;}const j=await api('/api/alerts/preview');$('preview').textContent=`Hoy: ${j.count} recordatorios programados. ${j.items.map(x=>x.name+' ('+x.days_before+' días)').join('; ')||'Ninguno'}. Esta vista no envía correos.`;}catch(e){$('preview').textContent=e.message}}
loadExpirations();

let importFile=null;
async function previewImport(){const f=$('importfile').files[0];if(!f){$('importstatus').textContent='Selecciona un Excel';return}importFile=f;const fd=new FormData();fd.append('file',f);$('importstatus').textContent='Analizando...';try{const r=await api('/api/import/preview',{method:'POST',body:fd});$('importstatus').textContent=JSON.stringify(r.stats,null,2)+'\nSolo vista previa: nada se ha modificado.';$('importcommit').disabled=false}catch(e){$('importstatus').textContent=e.message;$('importcommit').disabled=true}}
async function commitImport(){if(!importFile)return;if(!confirm('Se creará un respaldo y se agregarán los movimientos nuevos sin validar fechas. ¿Continuar?'))return;const fd=new FormData();fd.append('file',importFile);fd.append('confirm','IMPORTAR');$('importstatus').textContent='Importando...';try{const r=await api('/api/import/commit',{method:'POST',body:fd});$('importstatus').textContent='Importación terminada. Respaldo: '+r.backup+'\n'+JSON.stringify(r.stats,null,2);$('importcommit').disabled=true;dashboard();search()}catch(e){$('importstatus').textContent=e.message}}

async function loadEdits(id){try{const edits=await api('/api/vessels/'+id+'/edits');const el=document.createElement('div');el.innerHTML='<details class="detail-fold"><summary>Historial de correcciones</summary>'+(edits.length?'<ul class="history">'+edits.map(e=>'<li><b>'+escapeHtml(formatDate(e.changed_at))+'</b>: '+Object.entries(e.changes).map(([k,v])=>escapeHtml(k)+': '+escapeHtml(v.antes)+' → '+escapeHtml(v.despues)).join('; ')+'</li>').join('')+'</ul>':'<p class="muted">Sin correcciones registradas.</p>')+'</details>';if(selected===id){el.querySelector('details')?.classList.add('fold-edits');$('detail').appendChild(el)}}catch(e){console.error(e)}}

async function showUpcomingAlerts(){try{
 if(document.getElementById('tab-bdpruebas')){
  const d=await api('/api/push/schedule?days=30'),root=$('upcoming');
  root.innerHTML='<p><b>'+d.count+'</b> recordatorios de prueba para los próximos 30 días (SQLite y PostgreSQL DEMO). No se envían correos.</p>'+
   (d.events.length?'<div class="tablewrap"><table><thead><tr><th>Embarcación</th><th>Origen</th><th>Tipo</th><th>Fecha de aviso</th><th>Vencimiento</th><th>Anticipación</th></tr></thead><tbody>'+
   d.events.map(x=>'<tr><td>'+escapeHtml(x.vessel)+'</td><td>'+escapeHtml(x.source||'DEMO')+'</td><td>'+escapeHtml(x.category==='retorno_temporal'?'Retorno temporal':'Vencimiento')+'</td><td>'+formatDate(x.notify_on)+'</td><td>'+formatDate(x.deadline)+'</td><td>'+Number(x.days_before)+' día(s)</td></tr>').join('')+
   '</tbody></table></div>':'<p>No hay recordatorios programados en ese período.</p>');
  return;
 }
 const j=await api('/api/alerts/upcoming');const root=$('upcoming');root.innerHTML='<p><b>'+j.count+'</b> avisos programados para los próximos 30 días. Esta pantalla no envía correos.</p>'+(j.items.length?'<div class="tablewrap"><table><thead><tr><th>Embarcación</th><th>Fecha de aviso</th><th>Vencimiento</th><th>Anticipación</th></tr></thead><tbody>'+j.items.map(x=>'<tr><td>'+escapeHtml(x.name)+'</td><td>'+escapeHtml(x.category==='retorno_temporal'?'Retorno temporal':'Vencimiento')+'</td><td>'+formatDate(x.notify_on)+'</td><td>'+formatDate(x.expiry_date)+'</td><td>'+x.days_before+' día(s)</td></tr>').join('')+'</tbody></table></div>':'<p>No hay avisos programados en el período.</p>')+(j.truncated?'<p>Se muestran los primeros 1,000 avisos.</p>':'')
 }catch(e){$('upcoming').textContent=e.message}}
async function showAlertConfig(){try{const j=await api('/api/alerts/config');$('upcoming').textContent='Correo SMTP: '+(j.smtp_ready?'configurado':'sin configurar')+' · Destinatario administrativo: '+(j.admin_recipient?'configurado':'pendiente')+' · Envíos a clientes: '+(j.client_enabled?'habilitables':'desactivados')+' · Autorización de envío: '+(j.send_confirmed?'activada':'desactivada')+' · Android: pendiente hasta la fase final de nube.'}catch(e){$('upcoming').textContent=e.message}}

async function showReviewQueue(){const el=$('review-results');el.textContent='Consultando...';try{const j=await api('/api/review/queue?limit=100');el.innerHTML='<p>'+j.total+' expediente(s) requieren revisión. Se muestran hasta 100; no se activan avisos.</p><div class="tablewrap"><table><thead><tr><th>Embarcación</th><th>ST</th><th>Fecha</th><th>Motivo</th><th></th></tr></thead><tbody>'+j.items.map(x=>'<tr><td>'+escapeHtml(x.name)+'</td><td>'+escapeHtml(x.declaration)+'</td><td>'+escapeHtml(formatDate(x.expiry_date))+'</td><td>'+escapeHtml(x.reasons.join('; '))+'</td><td><button class="secondary" onclick="openVessel('+x.id+')">Abrir</button></td></tr>').join('')+'</tbody></table></div>'}catch(e){el.textContent=e.message}}
async function showRelated(){const el=$('review-results');el.textContent='Consultando...';try{const j=await api('/api/review/related');el.innerHTML='<p>'+j.total_groups+' grupo(s) con nombres coincidentes y distintas declaraciones ST. No se fusionan automáticamente.</p><div class="tablewrap"><table><thead><tr><th>Nombre</th><th>Expedientes</th><th>Ver fichas</th></tr></thead><tbody>'+j.items.map(x=>'<tr><td>'+escapeHtml(x.name)+'</td><td>'+x.count+'</td><td>'+x.vessels.map(v=>'<button class="secondary" onclick="openVessel('+v.id+')">'+escapeHtml(v.declaration)+'</button>').join(' ')+'</td></tr>').join('')+'</tbody></table></div>'}catch(e){el.textContent=e.message}}

// V18: alta de ingreso desde cero con lectura asistida y documento privado.
let permitToken='';
let permitReadVersion=0;
// Se borran los datos y la referencia al documento provisional cada vez que
// se cambia el archivo. Evita mezclar permisos cuando hay solicitudes en curso.
function clearNewEntry(keepFile=false){
 permitReadVersion++;
 permitToken='';
 for(const id of ['new-st','new-name','new-registration','new-captain','new-entry','new-expiry','new-email','new-notes'])$(id).value='';
 // La confirmación documental dejó de existir; no acceder a casillas retiradas.
 if(!keepFile)$('permit-file').value='';
 $('permit-status').textContent=keepFile?'Nuevo archivo seleccionado. Pulsa Leer permiso.':'Formulario limpio. Selecciona un permiso o ingresa los datos manualmente.';
 $('ocr-field-status').textContent='Pendiente de lectura.';
 $('new-message').textContent='';
 updateNewExpiry();
}
async function analyzePermit(){
 const f=$('permit-file').files[0],out=$('permit-status');
 if(!f){out.textContent='Selecciona el documento primero.';return}
 // Nueva lectura: nunca dejar sugerencias de un permiso anterior.
 clearNewEntry(true);
 const thisRead=++permitReadVersion;
 out.textContent='Leyendo el documento...';
 try{
  const data=new FormData();data.append('file',f);
  const r=await api('/api/documents/analyze',{method:'POST',body:data});
  if(thisRead!==permitReadVersion)return; // usuario cambió de archivo mientras leíamos
  permitToken=r.token;let changed=[];
  for(const [key,id] of [['declaration','new-st'],['name','new-name'],['captain','new-captain'],['email','new-email'],['start_date','new-entry']]){
   if(r.fields[key]){$(id).value=key==='start_date'?formatDate(r.fields[key]):r.fields[key];changed.push(key)}
  }
  updateNewExpiry();
  const labels={declaration:'Número ST',name:'Embarcación',captain:'Capitán / titular',email:'Correo',start_date:'Fecha de ingreso'};
  const statuses=['declaration','name','captain','start_date','email'].map(k=>{
   const status=r.fields[k]?(r.field_status&&r.field_status[k]==='revisar'?'Revisar':'Reconocido'):'No detectado';
   return labels[k]+': '+status;
  });
  $('ocr-field-status').textContent=statuses.join(' · ')+' · Verifica especialmente el correo y el nombre del titular.';
  out.textContent='Documento adjunto: '+r.filename+'. Campos sugeridos: '+(changed.join(', ')||'ninguno')+'. '+r.notes.join(' ');
 }catch(e){if(thisRead===permitReadVersion)out.textContent=e.message}
}
function updateNewExpiry(){try{const iso=toIsoDate($('new-entry').value,'Ingreso');const [y,m,d]=iso.split('-').map(Number);const dt=new Date(Date.UTC(y,m-1,d+90));$('new-expiry').value=String(dt.getUTCDate()).padStart(2,'0')+'/'+String(dt.getUTCMonth()+1).padStart(2,'0')+'/'+dt.getUTCFullYear()}catch(e){$('new-expiry').value=''}}
$('new-entry').addEventListener('input',updateNewExpiry);
$('permit-file').addEventListener('change',()=>clearNewEntry(true));
async function saveNewEntry(){
 const out=$('new-message');out.className='muted';
 try{
  const data={declaration:$('new-st').value.trim(),name:$('new-name').value.trim(),registration_number:$('new-registration').value.trim(),captain:$('new-captain').value.trim(),start_date:toIsoDate($('new-entry').value,'Ingreso'),email:$('new-email').value.trim(),notes:$('new-notes').value.trim(),document_token:permitToken,confirmed:true};
  if(document.getElementById('tab-bdpruebas')){
    if(data.email||data.document_token||document.getElementById('permit-file')?.files?.length)
      throw Error('En esta prueba no se guardan correos ni documentos. Usa datos ficticios y deja esos campos vacíos.');
    if(!/^DEMO-[A-Z0-9-]{2,24}$/i.test(data.declaration))
      throw Error('Para probar en la nube, el número ST debe comenzar con DEMO- (por ejemplo, DEMO-001).');
    if(!data.captain||data.captain.trim().length<2)
      throw Error('Introduce el nombre de un capitán ficticio.');
    const payload={registration:data.declaration,vessel_name:data.name,
      captain:data.captain,stage:'ingreso',entry_date:data.start_date,
      movement_date:data.start_date,notes:data.notes};
    const created=await api('/api/demo/vessels',{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    clearNewEntry();
    out.className='alert success';
    out.textContent='Ingreso ficticio DEMO guardado en PostgreSQL. No se enviaron correos ni se guardaron documentos.';
    if(typeof servamarDemoRefresh==='function')await servamarDemoRefresh();
    if(typeof servamarDemoEditById==='function')await servamarDemoEditById(created.id);
    return;
  }
  const result=await post('/api/vessels/new',data);
  clearNewEntry();out.className='alert success';out.textContent='Ingreso registrado. Vencimiento: '+formatDate(result.expiry_date)+'. No se enviaron correos.';
  await Promise.all([dashboard(),loadExpirations()]);await openVessel(result.id);
 }catch(e){out.className='alert error';out.textContent=e.message}
}
async function attachPermit(id){
 const f=$('attach-permit').files[0],out=$('doc-status');if(!f){out.textContent='Selecciona un documento.';return}
 try{const fd=new FormData();fd.append('file',f);await api('/api/vessels/'+id+'/document',{method:'POST',body:fd});out.textContent='Documento guardado.';await loadPermitDocuments(id)}catch(e){out.textContent=e.message}
}
async function loadPermitDocuments(id){
 const root=$('documents-list');if(!root)return;
 try{const rows=await api('/api/vessels/'+id+'/documents');root.innerHTML=rows.map(x=>'<li><a href="/api/documents/'+x.id+'/download">'+escapeHtml(x.file_name)+'</a> · '+escapeHtml(formatDate(x.uploaded_at))+'</li>').join('')||'<li>Sin documentos adjuntos.</li>'}catch(e){root.textContent=e.message}
}

async function previewManualClientEmail(){
 const status=$('manual-email-message'),box=$('manual-email-preview');
 status.textContent='Preparando editor del correo...';box.hidden=true;box.replaceChildren();
 try{
  const x=await api('/api/vessels/'+selected+'/manual-email-preview');
  box.innerHTML='<h3>Revisar y editar correo individual</h3>';
  const info=document.createElement('p');info.textContent='Destinatario: '+(x.to||'NO REGISTRADO')+' · Vencimiento: '+formatDate(x.expiry_date)+' · '+x.date_quality;box.appendChild(info);
  const field=(label,value,rows)=>{const wrap=document.createElement('label');wrap.className='field full';wrap.textContent=label;const el=rows?document.createElement('textarea'):document.createElement('input');el.value=value;el.style.width='100%';if(rows)el.rows=rows;wrap.appendChild(el);box.appendChild(wrap);return el};
  const subject=field('Asunto (puedes editarlo)',x.subject,0),body=field('Mensaje bilingüe (edita antes de enviar)',x.body,18);
  const footer=document.createElement('p');footer.className='muted';footer.textContent=x.eligible?'Los cambios de este mensaje NO afectan a otros clientes ni a la plantilla general.':'Envío no disponible: '+(x.reasons||[]).join('; ');box.appendChild(footer);
  if(x.eligible){const send=document.createElement('button');send.type='button';send.textContent='Revisar y enviar correo editado';send.onclick=()=>sendManualClientEmail(x,subject,body);box.appendChild(send)}
  box.hidden=false;status.textContent='Editor listo: ningún correo enviado.';
 }catch(e){status.textContent=e.message}
}
async function sendManualClientEmail(x,subjectField,bodyField){
 const status=$('manual-email-message');
 try{
  if(!x||!x.eligible)throw Error('Abre primero el editor y comprueba el permiso de envío.');
  const subject=subjectField.value.trim(),body=bodyField.value.trim();
  if(!subject||!body)throw Error('Asunto y mensaje obligatorios.');
  if(!confirm('¿Enviar a '+x.to+' sobre '+x.vessel+' con vencimiento '+formatDate(x.expiry_date)+'? Revisa el texto editado antes de continuar.'))return;
  const typed=prompt('Para confirmar el envío individual, escribe ENVIAR:','');if(typed!=='ENVIAR')return;
  const payload={confirmation:'ENVIAR',reviewed_email:true,reviewed_date:true,reviewed_content:true,
    historical_date_ack:x.date_quality!=='confirmado',subject,body};
  const result=await post('/api/vessels/'+selected+'/send-manual-email',payload);
  status.textContent=result.message+' a '+result.recipient+' · '+formatDate(result.expiry_date);$('manual-email-preview').hidden=true;
 }catch(e){status.textContent=e.message}
}
async function editGeneralMailTemplate(){
 const root=$('mail-template-panel'),status=$('mail-template-status');root.hidden=false;root.replaceChildren();
 try{
  const x=await api('/api/mail-template');
  const heading=document.createElement('p');heading.className='muted';heading.textContent='Variables disponibles: '+x.fields.map(f=>'{'+f+'}').join(', ')+'. Mantén {embarcacion} y {vencimiento} en el mensaje.';root.appendChild(heading);
  const subject=document.createElement('input');subject.id='global-mail-subject';subject.value=x.template.subject;subject.style.width='100%';
  const body=document.createElement('textarea');body.id='global-mail-body';body.value=x.template.body;body.rows=18;body.style.width='100%';
  const l1=document.createElement('label');l1.className='field full';l1.textContent='Asunto general';l1.appendChild(subject);root.appendChild(l1);
  const l2=document.createElement('label');l2.className='field full';l2.textContent='Formato y mensaje general (inglés primero, español después)';l2.appendChild(body);root.appendChild(l2);
  const save=document.createElement('button');save.textContent='Guardar plantilla general';save.onclick=async()=>{try{const r=await post('/api/mail-template',{subject:subject.value,body:body.value});status.textContent=r.message}catch(e){status.textContent=e.message}};
  const reset=document.createElement('button');reset.className='secondary';reset.textContent='Aplicar modelo cercano (inglés y español)';reset.onclick=async()=>{if(!confirm('¿Reemplazar tu plantilla guardada por el modelo cercano? Esta acción no se puede deshacer desde aquí.'))return;try{const r=await post('/api/mail-template/reset',{});subject.value=r.template.subject;body.value=r.template.body;status.textContent='Modelo cercano aplicado y guardado; revisa el texto antes de habilitar envíos.'}catch(e){status.textContent=e.message}};
  root.append(save,reset);status.textContent=x.custom?'Plantilla personalizada cargada.':'Plantilla predeterminada cargada.';
 }catch(e){status.textContent=e.message}
}

function toggleReportDates(){const show=$('report-period').value==='custom';document.querySelectorAll('.report-custom').forEach(x=>x.hidden=!show)}
async function downloadControl(fmt){const msg=$('report-status');try{
 const period=$('report-period').value,field=$('report-field').value;const params=new URLSearchParams({format:fmt,period,field});
 if(period==='custom'){params.set('from',toIsoDate($('report-from').value,'Desde'));params.set('to',toIsoDate($('report-to').value,'Hasta'))}
 const response=await fetch('/api/control/export?'+params.toString());
 if(!response.ok){const txt=await response.text();let detail='';try{detail=JSON.parse(txt).error}catch{detail='El servidor devolvió HTML en lugar del archivo. Revisa la terminal y ejecuta pip install -r requirements.txt'}throw Error(detail||'No se pudo exportar ('+response.status+')')}
 const blob=await response.blob();const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download='SERVAMAR_Control_'+new Date().toISOString().slice(0,10)+'.'+fmt;document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);msg.textContent='Archivo generado correctamente.';
 }catch(e){msg.textContent=e.message}}
async function showDateDiscrepancies(){const box=$('date-discrepancies');box.textContent='Revisando fechas...';try{
 const j=await api('/api/review/date-discrepancies');const s=j.summary;
 box.innerHTML='<p><b>'+s.initial_date_discrepancies+' diferencias</b> entre '+s.initial_dates_compared+' ingresos históricos con dos fechas legibles. '+s.entries_without_two_valid_dates+' registros sin ambas fechas válidas. Confirmados dentro de la aplicación: '+s.validated_in_system+' de '+s.total_fichas+'.</p><p>Estas diferencias son alertas de revisión, no correcciones automáticas.</p><div class="tablewrap"><table><thead><tr><th>ST</th><th>Embarcación</th><th>Ingreso</th><th>Vencimiento en archivo</th><th>Esperado (+90 d)</th><th>Diferencia</th><th></th></tr></thead><tbody>'+j.issues.map(x=>'<tr><td>'+escapeHtml(x.declaration)+'</td><td>'+escapeHtml(x.name)+'</td><td>'+formatDate(x.start_date)+'</td><td>'+formatDate(x.expiry_date)+'</td><td>'+formatDate(x.expected_date)+'</td><td>'+x.difference_days+' días</td><td><button class="secondary" onclick="openVessel('+x.vessel_id+')">Ver</button></td></tr>').join('')+'</tbody></table></div>';
 }catch(e){box.textContent=e.message}}

// V28: informar al operador de la versión realmente cargada.
fetch('/api/version').then(r=>r.json()).then(j=>{const v=document.getElementById('servamar-version');if(v)v.textContent='Versión '+j.version+' · datos persistentes'}).catch(()=>{});

// V32: se requiere selección expresa; no elimina movimientos importados ni cambia datos sin respaldo.
async function deleteMovement(historyId){
 if(!selected)return;
 if(!confirm('¿Eliminar este movimiento? Se creará un respaldo y el sistema restaurará el estado previo. Si es un retorno, se descontarán los días añadidos al vencimiento.'))return;
 if(!confirm('Confirmación final: ¿eliminar el movimiento seleccionado de este expediente?'))return;
 try{
  const j=await post('/api/vessels/'+selected+'/history/'+historyId+'/delete',{confirmation:'ELIMINAR MOVIMIENTO'});
  await Promise.all([dashboard(),search(),loadExpirations()]);
  await openVessel(selected);
  const m=$('message');if(m){m.className='alert success';m.textContent=j.message+' Respaldo: '+j.backup}
 }catch(e){const m=$('message');if(m){m.className='alert error';m.textContent=e.message}else alert(e.message)}
}

// V44: edición explícita del historial, sin volver a importar los Excel.
function editMovement(historyId){
 const r=movementRows.find(x=>Number(x.id)===Number(historyId));if(!r)return;
 const pane=$('movement-edit-panel');if(!pane)return;
 pane.innerHTML=`<section class="vessel-section vessel-movement" style="margin:10px 0;padding:14px"><h3>Modificar movimiento: ${escapeHtml(r.kind)}</h3>
 <div class="grid"><label class="field">Fecha del movimiento<input id="edit-event-date" placeholder="dd/mm/yyyy" value="${escapeHtml(formatDate(r.event_date)==='—'?'':formatDate(r.event_date))}"></label>
 <label class="field full">Observaciones<textarea id="edit-event-description" rows="3">${escapeHtml(r.description||'')}</textarea></label></div>
 <p class="muted">La fecha de arriba es la <b>fecha efectiva</b> que usa el contador. Si la observación importada menciona otra fecha, corrige la fecha efectiva y guarda. La anotación original permanecerá para auditoría.</p>
 <div class="actions"><button type="button" onclick="saveMovementEdit(${r.id})">Guardar modificación</button><button class="secondary" type="button" onclick="$('movement-edit-panel').innerHTML=''">Cancelar</button></div><p id="edit-movement-message"></p></section>`;
 pane.scrollIntoView({behavior:'smooth',block:'nearest'});
}
async function saveMovementEdit(historyId){
 try{
  const r=movementRows.find(x=>Number(x.id)===Number(historyId));if(!r)return;
  const dt=$('edit-event-date').value.trim();
  const value=dt?toIsoDate(dt,'Fecha del movimiento'):'';
  if(!confirm('¿Guardar esta corrección? Se creará un respaldo y se conservará la información anterior en auditoría.'))return;
  const result=await post('/api/vessels/'+selected+'/history/'+historyId+'/edit',{confirmation:'MODIFICAR MOVIMIENTO',event_date:value,description:$('edit-event-description').value});
  await Promise.all([dashboard(),search(),loadExpirations()]);await openVessel(selected);
  const m=$('message');if(m){m.className='alert success';m.textContent=result.message+(result.current_departure?' · Salida utilizada: '+formatDate(result.current_departure):'')+(result.note?' '+result.note:'')}
 }catch(e){const m=$('edit-movement-message');if(m){m.className='alert error';m.textContent=e.message}else alert(e.message)}
}


// V58 — Centro de alarmas Android / red local. Nunca envía correos ni modifica expedientes.
// La API devuelve únicamente recordatorios vigentes previstos para el día actual.
let androidAlarmBusy=false;
let androidAlarmLastSignature='';
function alarmContent(item){
 const category=item.category==='retorno_temporal'?'Retorno de salida temporal':'Vencimiento del permiso';
 return category+' · '+(item.name||'Embarcación')+' · '+(item.declaration||'')+' · '+formatDate(item.expiry_date);
}
async function refreshMobileAlarms(userRequested=false){
 if(androidAlarmBusy)return;
 if(document.visibilityState==='hidden'&&!userRequested)return;
 const list=$('android-alarm-list'),count=$('android-alarm-count'),status=$('android-alarm-status');
 if(!list||!count||!status)return;
 androidAlarmBusy=true;
 try{
  const data=await api('/api/alerts/preview');
  const rows=Array.isArray(data.items)?data.items:[];
  count.textContent=String(rows.length);
  status.textContent=rows.length?'Recordatorios programados para '+formatDate(data.date)+'.':'Sin recordatorios programados para hoy.';
  list.replaceChildren();
  rows.forEach(item=>{
   const row=document.createElement('div');row.className='mobile-alarm-item';
   const text=document.createElement('div');
   const title=document.createElement('strong');title.textContent=item.name||'Embarcación';
   const desc=document.createElement('span');desc.textContent=(item.category==='retorno_temporal'?'Retorno temporal':'Vencimiento')+' · '+(item.declaration||'')+' · '+formatDate(item.expiry_date);
   text.append(title,desc);
   const button=document.createElement('button');button.type='button';button.className='secondary small-btn';button.textContent='Abrir';
   button.addEventListener('click',()=>openVessel(Number(item.vessel_id)));
   row.append(text,button);list.appendChild(row);
  });
  const signature=data.date+'|'+rows.map(x=>[x.vessel_id,x.category||'permiso',x.days_before,x.expiry_date].join(':')).sort().join('|');
  if(rows.length&&signature!==androidAlarmLastSignature){
   androidAlarmLastSignature=signature;
   if(!userRequested&&typeof Notification!=='undefined'&&window.isSecureContext&&Notification.permission==='granted'){
    // Notification API only in supported secure contexts (HTTPS), while the page is open.
    try{new Notification('SERVAMAR: '+rows.length+' aviso(s) para hoy',{body:alarmContent(rows[0]),tag:'servamar-avisos-'+data.date});}catch(e){/* UI remains functional */}
   }
  }
 }catch(err){status.textContent='No se pudo consultar las alarmas: '+err.message;count.textContent='—';}
 finally{androidAlarmBusy=false;}
}
async function enableBrowserAlarms(){
 const status=$('android-alarm-status');
 if(!window.isSecureContext||!('Notification' in window)){
  status.textContent='En esta conexión HTTP por Wi-Fi, Android no permite notificaciones del sistema. Las alarmas dentro de la página sí funcionan. Para recibirlas con la app cerrada necesitaremos HTTPS + push o una app nativa.';
  return;
 }
 try{
  const permission=await Notification.requestPermission();
  status.textContent=permission==='granted'?'Permiso concedido. Notificaciones disponibles mientras la página esté abierta.':'Android no ha autorizado notificaciones del navegador.';
  if(permission==='granted')refreshMobileAlarms(true);
 }catch(err){status.textContent='No fue posible solicitar permisos: '+err.message;}
}
window.addEventListener('load',()=>{refreshMobileAlarms();window.setInterval(()=>refreshMobileAlarms(),60000);});
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')refreshMobileAlarms();});
