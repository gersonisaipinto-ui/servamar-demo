'use strict';
const $ = selector => document.querySelector(selector);
let editing = null, selected = null, deleting = null;
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
      node('p','Vencimiento: '+(displayDate(v.expiry_date)||'Sin fecha')),
      action('Editar',()=>openEdit(v.id)), action('Movimientos',()=>openHistory(v.id)),action('Eliminar',()=>openDelete(v.id)));
    return card;
  }));
  if(!data.vessels.length) $('#rows').append(node('p','No hay embarcaciones ficticias. Agrega la primera.'));
  await Promise.all([searchRecords(),loadExpiring()]);
}
function showEditor(v=null) {
  editing=v; $('#vessel-form').reset(); $('#editor-title').textContent=v?'Editar embarcación':'Agregar embarcación';
  if(v) for(const key of ['declaration','name','captain','start_date','expiry_date']) $('#vessel-form').elements[key].value=key.endsWith('_date')?displayDate(v[key]):v[key];
  $('#editor').hidden=false; $('#detail').hidden=true; selected=null; $('#editor-title').focus();
}
async function openEdit(id) { const data=await api('/api/test/vessels/'+id); showEditor(data.vessel); }
async function openHistory(id) {
  const [detail,history,contacts]=await Promise.all([api('/api/test/vessels/'+id),api('/api/test/vessels/'+id+'/movements'),api('/api/test/vessels/'+id+'/contacts')]);
  selected=detail.vessel; editing=null; $('#editor').hidden=true; $('#detail').hidden=false;
  $('#detail-name').textContent=selected.declaration+' · '+selected.name;
  $('#movements').replaceChildren(...history.movements.map(m=>{
    const item=node('article','','movement');
    item.append(node('strong',(labels[m.kind]||m.kind)+' · '+(displayDate(m.event_date)||'Sin fecha')));
    if(m.expiry_date)item.append(node('p','Vencimiento de referencia: '+displayDate(m.expiry_date)));
    if(m.description)item.append(node('p',m.description)); return item;
  }));
  if(!history.movements.length) $('#movements').append(node('p','Todavía no hay movimientos registrados.','muted'));
  $('#contacts').replaceChildren(...contacts.contacts.map(contact=>{
    const item=node('article','','movement');
    item.append(node('strong',contact.full_name+(contact.is_primary?' · Principal':'')),
      node('p',contact.contact_role+' · '+(contact.email||'Sin correo')+' · '+(contact.phone||'Sin teléfono')),
      action('Quitar contacto',async()=>{
        if(!confirm('¿Quitar este contacto ficticio?'))return;
        await api('/api/test/vessels/'+id+'/contacts/'+contact.id,'DELETE',{version:selected.version});
        message('Contacto eliminado.');await openHistory(id);
      }));
    return item;
  }));
  if(!contacts.contacts.length)$('#contacts').append(node('p','Sin contactos ficticios.','muted'));
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
$('#close-detail').onclick=()=>{ $('#detail').hidden=true; selected=null; };
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
    await api('/api/test/vessels/'+current.id+'/movements','POST',data);
    message('Movimiento guardado en el historial.'); await openHistory(current.id); await refresh();
  });
};
$('#delete-form').onsubmit=async event=>{
  event.preventDefault(); const form=event.target; if(!deleting)return;
  $('#confirm-delete').disabled=true;
  try {
    await api('/api/test/vessels/'+deleting.id,'DELETE',{version:deleting.version,confirm_declaration:form.elements.confirmation.value});
    $('#delete-dialog').close(); $('#editor').hidden=true; $('#detail').hidden=true; editing=null; selected=null;
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
    await api('/api/test/vessels/'+current.id+'/contacts','POST',data);
    message('Contacto ficticio guardado.');await openHistory(current.id);
  });
};

function searchParams() {
  const data=new FormData($('#search-form'));
  const params=new URLSearchParams();
  for(const key of ['q','month'])if(data.get(key))params.set(key,data.get(key));
  return params.toString();
}
async function searchRecords(){
  const result=await api('/api/test/search?'+searchParams());
  $('#search-count').textContent=result.count+' resultados'+(result.capped?' (límite de 1000)':'');
  $('#search-results').replaceChildren(...result.vessels.map(v=>{
    const item=node('article','','card');
    item.append(node('strong',v.name),node('p',v.declaration+' · '+v.captain),
      node('p','Vence: '+(displayDate(v.expiry_date)||'Sin fecha')),
      action('Abrir historial',()=>openHistory(v.id)));
    return item;
  }));
}
async function loadExpiring(){
  const result=await api('/api/test/expiring');
  $('#expiring-results').replaceChildren(...result.vessels.map(v=>{
    const item=node('article','','card');
    item.append(node('strong',v.name),node('p',v.declaration+' · '+v.captain),
      node('p',v.days_remaining+' días restantes · '+displayDate(v.expiry_date)));
    return item;
  }));
  if(!result.vessels.length)$('#expiring-results').append(node('p','No hay vencimientos en los próximos 30 días.','muted'));
}
$('#search-form').onsubmit=e=>{e.preventDefault();busy(e.target,searchRecords);};
$('#clear-search').onclick=()=>{$('#search-form').reset();searchRecords().catch(e=>message(e.message,true));};
$('#export-csv').onclick=()=>{window.location.href='/api/test/export.csv?'+searchParams();};
