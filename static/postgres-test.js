'use strict';
const $ = selector => document.querySelector(selector);
let editing = null, selected = null, deleting = null, editingMovement = null, editingContact = null;
let detailRequest = 0;
const labels = {ingreso:'Ingreso', ampliacion:'Ampliación', deposito:'Depósito', salida:'Salida', retorno:'Retorno', cierre:'Cierre'};
const displayDate = value => value ? value.slice(0, 10).split('-').reverse().join('/') : '';
function message(text, error=false) { $('#message').textContent=text; $('#message').classList.toggle('error',error); }
function node(tag, text, className) { const n=document.createElement(tag); n.textContent=text; if(className)n.className=className; return n; }
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
  try { await task(); } catch(error) { message(error.message,true); }
  finally { buttons.forEach(b=>b.disabled=false); }
}
function action(text, task, style='secondary') {
  const button=node('button',text,style);button.type='button';
  button.onclick=()=>busy(button,task); return button;
}
async function refresh() {
  const data=await api('/api/test/vessels');
  $('#rows').replaceChildren(...data.vessels.map(v=>{
    const card=node('article','', 'card');
    card.append(node('p',v.declaration,'registration'),node('h3',v.name),node('p','Capitán: '+v.captain),
      node('p','Etapa: '+(labels[v.stage]||v.stage)),node('p','Ingreso: '+(displayDate(v.start_date)||'Sin fecha')),
      node('p',v.plazo||('Vencimiento: '+(displayDate(v.expiry_date)||'Sin fecha'))),
      action('Editar',()=>openEdit(v.id)), action('Movimientos',()=>openHistory(v.id)),action('Eliminar',()=>openDelete(v.id)));
    return card;
  }));
  if(!data.vessels.length) $('#rows').append(node('p','No hay embarcaciones ficticias. Agrega la primera.'));
  await Promise.all([searchRecords(),loadExpiring()]);
}
function showEditor(v=null) {
  hideDetail(); editing=v; $('#vessel-form').reset(); $('#editor-title').textContent=v?'Editar embarcación':'Agregar embarcación';
  if(v) for(const key of ['declaration','name','captain','registration_number','start_date','expiry_date']) $('#vessel-form').elements[key].value=key.endsWith('_date')?displayDate(v[key]):v[key];
  $('#vessel-form').elements.calculation_mode.value=v?(v.calculation_mode||'manual'):'calculated';
  syncEditorMode();
  $('#editor').hidden=false; $('#detail').hidden=true; selected=null; $('#editor-title').focus();
}
async function openEdit(id) { const data=await api('/api/test/vessels/'+id); showEditor(data.vessel); }
async function openHistory(id) {
  const requestId=++detailRequest;
  const [detail,history,contacts,documents]=await Promise.all([api('/api/test/vessels/'+id),api('/api/test/vessels/'+id+'/movements'),api('/api/test/vessels/'+id+'/contacts'),api('/api/test/vessels/'+id+'/documents')]);
  if(requestId!==detailRequest)return;
  selected=detail.vessel; editing=null; $('#editor').hidden=true; $('#detail').hidden=false;
  $('#detail-name').textContent=selected.declaration+' · '+selected.name;
  $('#permit-summary').textContent=(selected.plazo||'Vencimiento manual: '+displayDate(selected.expiry_date))+(selected.days_added?' · '+selected.days_added+' días añadidos por retornos':'');
  $('#movement-help').textContent=selected.calculation_mode==='calculated'?'Cada cambio recalcula el historial completo. Retorno hasta el día 90 inclusive; cierre desde el día 91.':'Este expediente conserva fecha manual. Cambia el modo al editar la embarcación para aplicar el cálculo.';
  $('#movement-form').elements.expiry_date.disabled=selected.calculation_mode==='calculated';
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
      $('#movement-heading').textContent='Editar movimiento';form.elements.kind.focus();
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
  $('#movement-form').reset(); $('#detail-title').focus();
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
$('#cancel-edit').onclick=()=>{ $('#editor').hidden=true; editing=null; };
function hideDetail(){
  ++detailRequest;$('#detail').hidden=true;$('#document-section').hidden=true;$('#notification-section').hidden=true;
  selected=null;editingMovement=null;editingContact=null;
}
$('#close-detail').onclick=hideDetail;
$('#cancel-movement').onclick=()=>{editingMovement=null;$('#movement-form').reset();$('#movement-heading').textContent='Registrar movimiento ficticio';};
$('#contact-cancel').onclick=()=>{editingContact=null;$('#contact-form').reset();};
$('#cancel-delete').onclick=()=>$('#delete-dialog').close();
$('#vessel-form').onsubmit=event=>{
  event.preventDefault(); const form=event.target;
  busy(form,async()=>{
    const data=Object.fromEntries(new FormData(form)); const current=editing;
    if(current)data.version=current.version;
    await api('/api/test/vessels'+(current?'/'+current.id:''),current?'PUT':'POST',data);
    $('#editor').hidden=true; editing=null; message(current?'Cambios guardados.':'Embarcación ficticia agregada.'); await refresh();
  });
};
$('#movement-form').onsubmit=event=>{
  event.preventDefault(); const form=event.target; const current=selected;
  if(!current)return;
  busy(form,async()=>{
    const data=Object.fromEntries(new FormData(form)); data.version=current.version;
    await api('/api/test/vessels/'+current.id+'/movements'+(editingMovement?'/'+editingMovement.id:''),editingMovement?'PUT':'POST',data);
    message('Movimiento guardado en el historial.'); await openHistory(current.id); await refresh();
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
refresh().catch(error=>message(error.message,true));

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

function searchParams() {
  const data=new FormData($('#search-form'));
  const params=new URLSearchParams();
  for(const key of ['q','month','date_field','from','to'])if(data.get(key))params.set(key,data.get(key));
  return params.toString();
}
async function searchRecords(){
  const result=await api('/api/test/search?'+searchParams());
  $('#search-count').textContent=result.count+' resultados'+(result.capped?' (límite de 1000)':'');
  $('#search-results').replaceChildren(...result.vessels.map(v=>{
    const item=node('article','','card');
    item.append(node('strong',v.name),node('p',v.declaration+' · '+v.captain),
      node('p',v.plazo||('Vence: '+(displayDate(v.expiry_date)||'Sin fecha'))),
      action('Abrir historial',()=>openHistory(v.id)));
    return item;
  }));
}
async function loadExpiring(){
  const result=await api('/api/test/expiring');
  $('#expiring-results').replaceChildren(...result.vessels.map(v=>{
    const item=node('article','','card');
    item.append(node('strong',v.name),node('p',v.declaration+' · '+v.captain),
      node('p',v.plazo||(v.days_remaining+' días restantes · '+displayDate(v.expiry_date))));
    return item;
  }));
  if(!result.vessels.length)$('#expiring-results').append(node('p','No hay vencimientos en los próximos 30 días.','muted'));
}
$('#search-form').onsubmit=e=>{e.preventDefault();busy(e.target,searchRecords);};
$('#clear-search').onclick=()=>{$('#search-form').reset();searchRecords().catch(e=>message(e.message,true));};
async function download(path,filename){
  const response=await fetch(path,{credentials:'same-origin',cache:'no-store'});
  if(!response.ok){let result;try{result=await response.json();}catch{throw new Error('No se pudo descargar el archivo');}throw new Error(result.error||'No se pudo descargar el archivo');}
  const url=URL.createObjectURL(await response.blob());const link=document.createElement('a');link.href=url;link.download=filename;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
for(const format of ['csv','xlsx','pdf'])$('#export-'+format).onclick=e=>busy(e.target,()=>download('/api/test/export.'+format+'?'+searchParams(),'servamar-pruebas.'+format));
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
    $('#notification-reminders').textContent=result.warning+' '+result.reminders.map(r=>r.days_before+' días: '+displayDate(r.date)).join(' · ');
  });
};

function syncEditorMode(){
  const form=$('#vessel-form');const calculated=form.elements.calculation_mode.value==='calculated';
  form.elements.expiry_date.disabled=calculated;form.elements.start_date.required=calculated;
}
$('#vessel-form').elements.calculation_mode.onchange=syncEditorMode;
