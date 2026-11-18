'use strict';
const $ = selector => document.querySelector(selector);
let editing = null, selected = null, deleting = null, editingMovement = null, editingContact = null;
let detailRequest = 0, searchRequest = 0, searchSubmitted = false, reportRequest = 0, reportSubmitted = false;
let currentView='inicio', returnView='inicio';
let movementPreviewRequest=0, movementPreviewTimer;
const labels = {ingreso:'Ingreso', ampliacion:'Ampliación', deposito:'Depósito', salida:'Salida', retorno:'Retorno', cierre:'Cierre'};
const displayDate = value => value ? value.slice(0, 10).split('-').reverse().join('/') : '';
function message(text, error=false) { $('#message').textContent=text; $('#message').classList.toggle('error',error); }
function node(tag, text='', className) { const n=document.createElement(tag); n.textContent=text; if(className)n.className=className; return n; }
async function api(path, method='GET', body) {
  const headers={'Accept':'application/json'};
  if(body!==undefined) { headers['Content-Type']='application/json'; headers['X-CSRF-Token']=$('meta[name="csrf-token"]').content; }
  const response=await fetch(path,{method,headers,body:body===undefined?undefined:JSON.stringify(body),credentials:'same-origin',cache:'no-store'});
  let result; try { result=await response.json(); } catch { throw new Error('No se pudo leer la respuesta. Recarga la página e inicia sesión.'); }
  if(!response.ok) throw new Error(result.error || 'No se pudo completar la operación');
  return result;
}
async function busy(element, task) {
  const buttons=element.matches('button')?[element]:[...element.querySelectorAll('button')];
  buttons.forEach(b=>b.disabled=true);
  try { await task(); } catch(error) { message(error.message,true); if(element.id==='movement-form')$('#movement-feedback').textContent=error.message; }
  finally { buttons.forEach(b=>b.disabled=false); }
}
function action(text, task, style='secondary') {
  const button=node('button',text,style);button.type='button';
  button.onclick=()=>busy(button,task); return button;
}
function showView(view, focus=false){
  const panel=document.getElementById('tab-'+view);if(!panel)return;
  for(const item of document.querySelectorAll('.view-panel'))item.hidden=item!==panel;
  for(const button of document.querySelectorAll('.tabs [data-view]')){
    const active=button.dataset.view===(view==='expediente'?returnView:view);
    button.classList.toggle('active',active);
    if(active)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');
  }
  currentView=view;
  if(focus){const heading=panel.querySelector('h2');if(heading){heading.tabIndex=-1;heading.focus();}}
}
function renderVessels(target,vessels,mode='list',empty='No hay embarcaciones para estos filtros.'){
  const compact=mode==='upcoming'||mode==='notices';
  target.replaceChildren(...vessels.map(v=>{
    const row=node('tr');
    function cell(label,content){const td=node('td');td.dataset.label=label;td.append(content);row.append(td);return td;}
    const name=node('div');name.append(node('strong',v.name));if(compact)name.append(node('small',v.declaration));
    cell('Embarcación',name);
    if(!compact){cell('Número ST',v.declaration);cell('Registro',v.registration_number||'—');}
    cell('Capitán',v.captain||'Sin registrar');
    if(!compact){cell('Etapa',node('span',labels[v.stage]||v.stage,'badge '+(labels[v.stage]?v.stage:'')));cell('Ingreso',displayDate(v.start_date)||'Sin fecha');}
    cell('Plazo',v.plazo||('Vence: '+(displayDate(v.expiry_date)||'Sin fecha')));
    const actions=node('div','','row-actions');
    if(mode==='list')actions.append(action('Editar',()=>openEdit(v.id)),action('Movimientos',()=>openHistory(v.id)),action('Eliminar',()=>openDelete(v.id),'danger'));
    else actions.append(action(mode==='notices'?'Ver avisos':'Ver expediente',()=>openHistory(v.id,mode==='notices')));
    cell('Acciones',actions);return row;
  }));
  if(!vessels.length){const row=node('tr'),td=node('td',empty,'muted');td.colSpan=compact?4:8;row.append(td);target.append(row);}
}
async function refresh() {
  const data=await api('/api/test/vessels');
  renderVessels($('#rows'),data.vessels,'list','Todavía no hay embarcaciones ficticias. Registra el primer ingreso.');
  renderVessels($('#notice-vessels'),data.vessels,'notices','Registra una embarcación para consultar sus avisos.');
  $('#records-count').textContent=' ('+data.vessels.length+')';
  $('#total-vessels').textContent=data.vessels.length;
  $('#away-vessels').textContent=data.vessels.filter(v=>v.stage==='salida').length;
  await Promise.all([searchSubmitted?searchRecords():Promise.resolve(),reportSubmitted?previewReport():Promise.resolve(),loadExpiring()]);
}
function showEditor(v=null) {
  returnView=currentView==='expediente'?returnView:currentView==='nuevo'?'inicio':currentView;
  hideDetail(); editing=v; $('#vessel-form').reset(); $('#editor-title').textContent=v?'Editar embarcación':'Agregar embarcación';
  if(v) for(const key of ['declaration','name','captain','registration_number','start_date','expiry_date']) $('#vessel-form').elements[key].value=key.endsWith('_date')?displayDate(v[key]):v[key];
  $('#vessel-form').elements.calculation_mode.value=v?(v.calculation_mode||'manual'):'calculated';
  syncEditorMode();
  $('#editor').hidden=false; $('#detail').hidden=true; selected=null;showView('nuevo');$('#editor-title').focus();
}
async function openEdit(id) { const data=await api('/api/test/vessels/'+id); showEditor(data.vessel); }
async function openHistory(id, focusNotices=false) {
  const requestId=++detailRequest;
  const [detail,history,contacts,documents,plan]=await Promise.all([api('/api/test/vessels/'+id),api('/api/test/vessels/'+id+'/movements'),api('/api/test/vessels/'+id+'/contacts'),api('/api/test/vessels/'+id+'/documents'),api('/api/test/vessels/'+id+'/notifications/plan')]);
  if(requestId!==detailRequest)return;
  if(currentView!=='expediente')returnView=currentView;
  showView('expediente');
  selected=detail.vessel; editing=null; $('#editor').hidden=true; $('#detail').hidden=false;
  $('#detail-name').textContent=selected.declaration+' · '+selected.name;
  renderNotificationPlan(plan);
  $('#automatic-notification-status').textContent='Los avisos de correo y notificación siguen el vencimiento actual: '+(displayDate(selected.expiry_date)||'sin fecha')+'. Los envíos reales siguen deshabilitados en pruebas.';
  $('#permit-summary').textContent=(selected.plazo||'Vencimiento manual: '+displayDate(selected.expiry_date))+(selected.days_added?' · '+selected.days_added+' días añadidos por retornos':'');
  $('#movement-help').textContent=selected.calculation_mode==='calculated'?'Cada cambio recalcula el historial completo. Retorno hasta el día 90 inclusive; cierre desde el día 91.':'Este expediente tiene fecha manual. Al guardar con el cálculo activado, se validará su historial y se actualizarán el permiso y los recordatorios juntos.';
  $('#movement-calculation-option').hidden=selected.calculation_mode==='calculated';
  const last=history.movements.at(-1);
  $('#last-movement').textContent=last?'Último movimiento: '+(labels[last.kind]||last.kind)+' el '+displayDate(last.event_date):'Sin movimientos.';
  $('#document-section').hidden=false;$('#notification-section').hidden=false;
  $('#notification-subject').textContent='';$('#notification-body').textContent='';$('#notification-reminders').textContent='';
  $('#documents').replaceChildren(...documents.documents.map(d=>{
    const item=node('article','','movement');
    item.append(node('strong',d.filename+(d.archived_at?' · Archivado':'')),node('p',d.document_type+' · '+(d.size_bytes===null?'Archivo aún no cargado':d.size_bytes+' bytes')));
    if(d.size_bytes!==null)item.append(action('Descargar',()=>download('/api/test/vessels/'+id+'/documents/'+d.id+'/download',d.filename)));
    item.append(action(d.archived_at?'Restaurar':'Archivar',async()=>{
      await api('/api/test/vessels/'+id+'/documents/'+d.id,'PATCH',{version:selected.version,archived:!d.archived_at});
      message(d.archived_at?'Documento restaurado.':'Documento archivado.');await openHistory(id);
    }));return item;
  }));
  if(!documents.documents.length)$('#documents').append(node('p','Sin documentos ficticios.','muted'));
  $('#document-form').reset();
  $('#movements').replaceChildren(...history.movements.map(m=>{
    const item=node('article','','movement');
    item.append(node('strong',(labels[m.kind]||m.kind)+' · '+(displayDate(m.event_date)||'Sin fecha')));
    if(m.expiry_date)item.append(node('p','Vencimiento de referencia: '+displayDate(m.expiry_date)));
    if(m.description)item.append(node('p',m.description));
    item.append(action('Editar movimiento',()=>{
      editingMovement=m;
      const form=$('#movement-form');
      for(const key of ['kind','event_date','expiry_date','description'])form.elements[key].value=key.endsWith('_date')?displayDate(m[key]):m[key]||'';
      syncDates(form);queueMovementPreview();$('#movement-heading').textContent='Editar movimiento';form.elements.kind.focus();
    }),action('Eliminar movimiento',async()=>{
      const confirmation=prompt('Escribe '+selected.declaration+' para eliminar este movimiento. Se conservará su auditoría.');
      if(confirmation===null)return;
      await api('/api/test/vessels/'+id+'/movements/'+m.id,'DELETE',{version:selected.version,confirm_declaration:confirmation});
      message('Movimiento eliminado; auditoría conservada.');await openHistory(id);await refresh();
    }));return item;
  }));
  if(!history.movements.length) $('#movements').append(node('p','Todavía no hay movimientos registrados.','muted'));
  $('#contacts').replaceChildren(...contacts.contacts.map(contact=>{
    const item=node('article','','movement');
    item.append(node('strong',contact.full_name+(contact.is_primary?' · Principal':'')),
      node('p',contact.contact_role+' · '+(contact.email||'Sin correo')+' · '+(contact.phone||'Sin teléfono')),
      action('Editar contacto',()=>{
        editingContact=contact;const form=$('#contact-form');
        for(const key of ['contact_role','full_name','email','phone'])form.elements[key].value=contact[key]||'';
        form.elements.is_primary.checked=contact.is_primary;form.elements.full_name.focus();
      }),
      action('Quitar contacto',async()=>{
        if(!confirm('¿Quitar este contacto ficticio?'))return;
        await api('/api/test/vessels/'+id+'/contacts/'+contact.id,'DELETE',{version:selected.version});
        message('Contacto eliminado.');await openHistory(id);
      }));
    return item;
  }));
  if(!contacts.contacts.length)$('#contacts').append(node('p','Sin contactos ficticios.','muted'));
  editingContact=null;editingMovement=null;$('#movement-heading').textContent='Registrar movimiento ficticio';
  $('#contact-form').reset();
  resetMovementForm();
  (focusNotices?$('#notifications-title'):$('#detail-title')).focus();
}
async function openDelete(id) {
  const data=await api('/api/test/vessels/'+id); deleting=data.vessel;
  $('#delete-form').reset(); $('#delete-error').textContent='';
  const blocked=Object.values(data.dependencies).some(count=>count>0);
  $('#delete-explanation').textContent=blocked
    ? 'No se puede eliminar '+deleting.declaration+': tiene '+data.dependencies.movements+' movimientos, '+data.dependencies.alerts+' alertas y otros registros vinculados. Se conservarán todos los registros.'
    : 'Se eliminará '+deleting.declaration+' · '+deleting.name+'. La acción conserva un registro de auditoría.';
  $('#confirm-delete').disabled=blocked; $('#delete-form').elements.confirmation.disabled=blocked;
  $('#delete-dialog').showModal();
}
$('#new-vessel').onclick=()=>showEditor();
$('#refresh').onclick=event=>busy(event.target,refresh);
$('#cancel-edit').onclick=()=>{ $('#editor').hidden=true; editing=null;showView(returnView,true); };
function hideDetail(){
  ++movementPreviewRequest;clearTimeout(movementPreviewTimer);
  ++detailRequest;$('#detail').hidden=true;$('#document-section').hidden=true;$('#notification-section').hidden=true;
  selected=null;editingMovement=null;editingContact=null;
}
$('#close-detail').onclick=()=>{hideDetail();showView(returnView,true);};
$('#cancel-movement').onclick=()=>{editingMovement=null;resetMovementForm();$('#movement-heading').textContent='Registrar movimiento ficticio';};
$('#contact-cancel').onclick=()=>{editingContact=null;$('#contact-form').reset();};
$('#cancel-delete').onclick=()=>$('#delete-dialog').close();
$('#vessel-form').onsubmit=event=>{
  event.preventDefault(); const form=event.target;
  busy(form,async()=>{
    const data=Object.fromEntries(new FormData(form)); const current=editing;
    if(current)data.version=current.version;
    await api('/api/test/vessels'+(current?'/'+current.id:''),current?'PUT':'POST',data);
    $('#editor').hidden=true; editing=null;showView(returnView,true); message(current?'Cambios guardados.':'Embarcación ficticia agregada.'); await refresh();
  });
};
$('#movement-form').onsubmit=event=>{
  event.preventDefault(); const form=event.target; const current=selected;
  if(!current)return;
  busy(form,async()=>{
    ++movementPreviewRequest;clearTimeout(movementPreviewTimer);$('#movement-feedback').textContent='';
    const data=movementData(), movementId=editingMovement?.id;
    const result=await api('/api/test/vessels/'+current.id+'/movements'+(movementId?'/'+movementId:''),movementId?'PUT':'POST',data);
    message(result.projection_applied?'Movimiento guardado. Vencimiento: '+displayDate(result.vessel.expiry_date)+'. Recordatorios recalculados; sin envíos.':'Movimiento de referencia guardado. La fecha manual del permiso se conserva.');
    await openHistory(current.id); await refresh();
  });
};
$('#delete-form').onsubmit=async event=>{
  event.preventDefault(); const form=event.target; if(!deleting)return;
  $('#confirm-delete').disabled=true;
  try {
    await api('/api/test/vessels/'+deleting.id,'DELETE',{version:deleting.version,confirm_declaration:form.elements.confirmation.value});
    $('#delete-dialog').close(); $('#editor').hidden=true; hideDetail(); editing=null; selected=null;
    message('Embarcación ficticia eliminada.'); await refresh();
  } catch(error) { $('#delete-error').textContent=error.message; }
  finally { $('#confirm-delete').disabled=false; }
};

$('#contact-form').onsubmit=event=>{
  event.preventDefault();const form=event.target;const current=selected;
  if(!current)return;
  busy(form,async()=>{
    const data=Object.fromEntries(new FormData(form));
    data.is_primary=form.elements.is_primary.checked;data.version=current.version;
    await api('/api/test/vessels/'+current.id+'/contacts'+(editingContact?'/'+editingContact.id:''),editingContact?'PUT':'POST',data);
    message('Contacto ficticio guardado.');await openHistory(current.id);
  });
};

function searchParams(form=$('#search-form')) {
  const data=new FormData(form);
  const params=new URLSearchParams();
  for(const key of ['q','month','date_field','stage','from','to'])if(data.get(key))params.set(key,data.get(key));
  return params.toString();
}
async function searchRecords(){
  const requestId=++searchRequest;
  const result=await api('/api/test/search?'+searchParams());
  if(requestId!==searchRequest)return;
  $('#search-count').textContent=result.count+' resultados'+(result.capped?' (límite de 1000)':'');
  renderVessels($('#search-results'),result.vessels,'search');
}
async function loadExpiring(){
  const result=await api('/api/test/expiring');
  renderVessels($('#expiring-results'),result.vessels,'upcoming','No hay vencimientos en los próximos 30 días.');
  $('#due-vessels').textContent=result.vessels.length+(result.capped?'+':'');
}
async function previewReport(){
  const requestId=++reportRequest;
  const result=await api('/api/test/search?'+searchParams($('#report-form')));
  if(requestId!==reportRequest)return;
  $('#report-count').textContent=result.count+' embarcaciones'+(result.capped?' (límite de 1000; reduce el período antes de descargar)':'');
  renderVessels($('#report-results'),result.vessels,'report');
}
$('#report-form').onsubmit=e=>{e.preventDefault();reportSubmitted=true;busy(e.target,previewReport);};
$('#clear-report').onclick=()=>{$('#report-form').reset();reportSubmitted=false;++reportRequest;$('#report-count').textContent='Selecciona un período para revisar el control antes de descargarlo.';$('#report-results').replaceChildren();};
$('#search-to-report').onclick=()=>{
  for(const key of ['q','month','date_field','stage','from','to'])$('#report-form').elements[key].value=$('#search-form').elements[key].value;
  syncDates($('#report-form'));reportSubmitted=false;++reportRequest;$('#report-results').replaceChildren();
  $('#report-count').textContent='Filtros copiados desde Buscar. Pulsa Vista previa para revisar el control.';showView('exportar',true);
};
$('#search-form').onsubmit=e=>{e.preventDefault();searchSubmitted=true;busy(e.target,searchRecords);};
$('#clear-search').onclick=()=>{$('#search-form').reset();searchSubmitted=false;++searchRequest;$('#search-count').textContent='Usa los filtros y pulsa Buscar para consultar otros expedientes.';$('#search-results').replaceChildren();};
async function download(path,filename){
  const response=await fetch(path,{credentials:'same-origin',cache:'no-store'});
  if(!response.ok){let result;try{result=await response.json();}catch{throw new Error('No se pudo descargar el archivo');}throw new Error(result.error||'No se pudo descargar el archivo');}
  const url=URL.createObjectURL(await response.blob());const link=document.createElement('a');link.href=url;link.download=filename;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
for(const format of ['csv','xlsx','pdf'])$('#export-'+format).onclick=e=>busy(e.target,()=>download('/api/test/export.'+format+'?'+searchParams($('#report-form')),'servamar-pruebas.'+format));
$('#document-form').onsubmit=event=>{
  event.preventDefault();const form=event.target;const current=selected;if(!current)return;
  busy(form,async()=>{
    const file=form.elements.document.files[0];
    if(!file||file.size>2*1024*1024)throw new Error('Selecciona un archivo ficticio de hasta 2 MB');
    const encoded=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(new Error('No se pudo leer el archivo'));reader.readAsDataURL(file);});
    await api('/api/test/vessels/'+current.id+'/documents','POST',{version:current.version,filename:file.name,document_type:form.elements.document_type.value,content_base64:encoded,fictional_confirmed:form.elements.fictional_confirmed.checked});
    message('Documento ficticio guardado.');await openHistory(current.id);
  });
};
$('#preview-notification').onclick=event=>{
  const current=selected;if(!current)return;
  busy(event.target,async()=>{
    const result=await api('/api/test/vessels/'+current.id+'/notifications/preview');
    if(!selected||selected.id!==current.id)return;
    $('#notification-subject').textContent=result.subject;$('#notification-body').textContent=result.body;
    $('#notification-reminders').textContent=result.warning+' '+result.reminders.map(r=>r.days_before+' días: '+displayDate(r.date)+(r.status==='elapsed'?' (fecha pasada)':'')).join(' · ');
  });
};

function syncEditorMode(){
  const form=$('#vessel-form');const calculated=form.elements.calculation_mode.value==='calculated';
  form.elements.expiry_date.disabled=calculated;form.elements.start_date.required=calculated;
  form.elements.expiry_date.closest('.date-control').parentElement.hidden=calculated;
  $('#initial-expiry-field').hidden=!calculated;updateInitialExpiry();syncDates(form);
}
$('#vessel-form').elements.calculation_mode.onchange=syncEditorMode;
function updateInitialExpiry(){
  const iso=dateISO($('#vessel-form').elements.start_date.value);
  const value=iso?new Date(iso+'T12:00:00Z'):null;
  if(value)value.setUTCDate(value.getUTCDate()+90);
  $('#initial-expiry').value=value?displayDate(value.toISOString()):'';
}
function movementData(){
  const form=$('#movement-form'),data=Object.fromEntries(new FormData(form));
  data.version=selected.version;data.apply_calculation=selected.calculation_mode==='calculated'||form.elements.apply_calculation.checked;
  if(editingMovement)data.movement_id=editingMovement.id;
  return data;
}
function resetMovementForm(){
  const form=$('#movement-form');form.reset();
  form.elements.kind.value=({ingreso:'ampliacion',ampliacion:'deposito',salida:'retorno',cierre:'ingreso'})[selected?.stage]||'cierre';
  syncDates(form);queueMovementPreview();
}
function queueMovementPreview(){
  const sequence=++movementPreviewRequest;clearTimeout(movementPreviewTimer);
  if(!selected)return;
  const form=$('#movement-form'),calculated=selected.calculation_mode==='calculated'||form.elements.apply_calculation.checked;
  const extension=form.elements.kind.value==='ampliacion';
  form.elements.event_date.required=!extension;
  document.querySelector('label[for="'+form.elements.event_date.id+'"]').firstChild.textContent=extension?'Fecha de autorización (opcional)':'Fecha del movimiento';
  form.elements.expiry_date.disabled=calculated;
  form.elements.expiry_date.closest('.date-control').parentElement.hidden=calculated;syncDates(form);
  $('#movement-calculated-field').hidden=!calculated;
  $('#movement-calculated-expiry').value='';$('#movement-feedback').textContent='';
  if(!calculated){$('#movement-preview').textContent='Solo se guardará una referencia en el historial. La fecha manual del permiso no cambiará.';return;}
  if(!dateISO(form.elements.event_date.value)&&!(extension&&!form.elements.event_date.value)){
    $('#movement-preview').textContent='Completa una fecha válida para ver el vencimiento calculado.';return;
  }
  $('#movement-preview').textContent='Calculando vencimiento…';
  const current=selected,data=movementData();
  movementPreviewTimer=setTimeout(async()=>{
    try{
      const result=await api('/api/test/vessels/'+current.id+'/movements/preview','POST',data);
      if(sequence!==movementPreviewRequest||selected?.id!==current.id)return;
      const projected=result.projection;
      $('#movement-calculated-expiry').value=displayDate(projected.expiry_date);
      $('#movement-preview').textContent=projected.explanation+' Fecha del movimiento: '+displayDate(result.effective_event_date)+'.'+
        (result.mode_will_change?' Al guardar se activará el cálculo de este expediente.':'')+
        ' Los avisos seguirán el vencimiento vigente a 30, 15 y 1 días; sin envíos.';
    }catch(error){
      if(sequence!==movementPreviewRequest||selected?.id!==current.id)return;
      $('#movement-preview').textContent='No se puede calcular este movimiento.';$('#movement-feedback').textContent=error.message;
    }
  },200);
}
$('#movement-form').addEventListener('input',event=>{if(event.target.name!=='description')queueMovementPreview();});
$('#vessel-form').addEventListener('input',updateInitialExpiry);

// Group channels only when their date, deadline and status match. Sent and cancelled
// entries remain distinct from future plans, including after undoing a movement.
function renderNotificationPlan(result){
  const channels={email:'Correo',push:'Android / push',windows:'Windows'};
  const statuses={planned:'Planificado · sin envío',cancelled:'Cancelado',elapsed:'Fecha pasada',sent:'Ya enviado'};
  const groups=new Map();
  for(const plan of result.plans){
    const key=[plan.expiry_date,plan.date,plan.days_before,plan.status].join('|');
    if(!groups.has(key))groups.set(key,{...plan,channels:new Set()});
    groups.get(key).channels.add(channels[plan.channel]||plan.channel);
  }
  const current=[],history=[];
  for(const plan of groups.values()){
    const card=node('article','','card');
    card.append(node('strong',displayDate(plan.date)+' · '+plan.days_before+' días antes'),
      node('p',statuses[plan.status]||plan.status,'plan-status '+plan.status),
      node('p','Vencimiento: '+displayDate(plan.expiry_date)),node('p',[...plan.channels].join(' · ')));
    (plan.status==='planned'&&plan.expiry_date===result.expiry_date?current:history).push(card);
  }
  $('#notification-plan').replaceChildren(...current);
  if(!current.length)$('#notification-plan').append(node('p','No hay avisos futuros pendientes para el vencimiento actual.','muted'));
  $('#notification-history-rows').replaceChildren(...history);
  $('#notification-history-count').textContent=' ('+history.length+')';
  $('#notification-history').hidden=!history.length;
  $('#notification-plan-limit').hidden=!result.capped;
}

// Date text is the submitted value. The native calendar has no name and uses ISO
// only to communicate with the browser, avoiding locale and timezone conversion.
function dateISO(value){
  const match=/^(\d{2})\/(\d{2})\/(\d{4})$/.exec(value);
  if(!match)return '';
  const [,day,month,year]=match;
  const iso=year+'-'+month+'-'+day;
  const parsed=new Date(iso+'T12:00:00Z');
  return !Number.isNaN(parsed.getTime())&&parsed.toISOString().slice(0,10)===iso?iso:'';
}
function syncDates(scope){
  for(const input of scope.querySelectorAll('[data-date]')){
    const calendar=document.getElementById(input.id+'-calendar');
    if(!calendar)continue;
    calendar.value=dateISO(input.value);calendar.disabled=input.disabled;
    input.setCustomValidity(input.value.length===10&&!calendar.value?'Escribe una fecha válida en dd/mm/yyyy.':'');
  }
}
function enhanceDates(){
  for(const [index,input] of [...document.querySelectorAll('[data-date]')].entries()){
    const label=input.closest('label');const caption=label.textContent.trim();
    input.id=input.id||'date-'+index;label.htmlFor=input.id;
    const field=document.createElement('div');label.before(field);field.append(label);
    const wrapper=document.createElement('span');wrapper.className='date-control';
    const calendar=document.createElement('input');calendar.type='date';calendar.className='date-calendar';
    calendar.id=input.id+'-calendar';calendar.setAttribute('aria-label','Calendario: '+caption);
    calendar.title='Elegir '+caption.toLowerCase()+' en calendario';
    wrapper.append(input,calendar);field.append(wrapper);
    input.addEventListener('input',event=>{
      if(!event.inputType||!event.inputType.startsWith('delete')){
        const raw=input.value,iso=/^\d{4}-\d{2}-\d{2}$/.test(raw);
        const digitsBefore=raw.slice(0,input.selectionStart).replace(/\D/g,'').length;
        const digits=(iso?displayDate(raw):raw).replace(/\D/g,'').slice(0,8);
        input.value=digits.slice(0,2)+(digits.length>2?'/'+digits.slice(2,4):'')+(digits.length>4?'/'+digits.slice(4):'');
        const position=iso?input.value.length:digitsBefore+(digitsBefore>2?1:0)+(digitsBefore>4?1:0);
        input.setSelectionRange(position,position);
      }
      syncDates(input.form);
    });
    calendar.addEventListener('input',()=>{input.value=displayDate(calendar.value);syncDates(input.form);});
  }
  for(const form of document.forms)form.addEventListener('reset',()=>queueMicrotask(()=>syncDates(form)));
  syncDates(document);
}
for(const button of document.querySelectorAll('.tabs [data-view]'))button.onclick=()=>{
  ++detailRequest;
  if(button.dataset.view==='nuevo'&&$('#editor').hidden)showEditor();else showView(button.dataset.view,true);
};
enhanceDates();
refresh().catch(error=>message(error.message,true));
