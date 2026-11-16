(function(){
 'use strict';
 let records=[],deletedRecords=[],editing=null;
 const $=id=>document.getElementById(id);
 const status=(t,error=false)=>{const el=$('dbdemo-status');if(el){el.textContent=t;el.style.color=error?'#9b2121':'';}};
 const fmt=d=>{const m=/^(\d{4})-(\d{2})-(\d{2})$/.exec(String(d||''));return m?m[3]+'/'+m[2]+'/'+m[1]:(d||'—');};
 const iso=d=>{const m=/^(\d{2})\/(\d{2})\/(\d{4})$/.exec(String(d||'').trim());if(!m)throw Error('Escribe fechas como dd/mm/yyyy');const x=m[3]+'-'+m[2]+'-'+m[1];const q=new Date(x+'T12:00:00Z');if(Number.isNaN(q.getTime())||q.toISOString().slice(0,10)!==x)throw Error('Fecha inválida: '+d);return x;};
 const api=async(path,method='GET',payload)=>{
   const r=await fetch(path,{method,credentials:'same-origin',headers:{'Accept':'application/json','Content-Type':'application/json'},...(payload?{body:JSON.stringify(payload)}:{})});
   const j=await r.json();if(!r.ok)throw Error(j.error||('Error '+r.status));return j;
 };
 const stageNames={ingreso:'Ingreso inicial',ampliacion:'Ampliación',deposito:'Depósito aduanero',salida:'Salida temporal',cierre:'Permiso cerrado'};
 const movementNames={ampliacion:'Ampliación',deposito:'Ingreso a depósito',salida:'Salida temporal',retorno:'Retorno de salida temporal',cierre:'Cierre del permiso'};
 const dueLabel=r=>r.stage==='salida'?'Cumple 90 días fuera':r.stage==='cierre'?'Permiso cerrado':'Vencimiento';
 const dueText=r=>r.stage==='cierre'?'Permiso cerrado':fmt(r.due_date);
 const fields=['registration','vessel_name','captain','stage','entry_date','movement_date','notes'];
 const values=()=>{
  const obj={};
  for(const k of fields)obj[k]=$('dbdemo-'+k).value.trim();
  obj.entry_date=iso(obj.entry_date);obj.movement_date=iso(obj.movement_date);
  return obj;
 };
 const setRecord=r=>{
  editing=r||null;
  $('dbdemo-title').textContent=r?'Modificar registro ficticio':'Nuevo registro ficticio';
  $('dbdemo-save').textContent=r?'Guardar modificaciones':'Guardar nuevo registro';
  for(const k of fields){const v=r?r[k]:(k==='stage'?'ingreso':'');$('dbdemo-'+k).value=(k==='entry_date'||k==='movement_date')?fmt(v).replace('—',''):(v||'');}
  $('dbdemo-cancel').hidden=!r;
  $('dbdemo-stage').disabled=!!r;
  $('dbdemo-movement-panel').hidden=!r;
  $('dbdemo-movement-history').replaceChildren();
  if(r){
    $('dbdemo-movement-selected').textContent=r.registration+' · '+r.vessel_name+' · etapa actual: '+(stageNames[r.stage]||r.stage)+' · '+dueLabel(r)+': '+dueText(r);
    $('dbdemo-movement-event').value=fmt(r.movement_date);
  }
  status(r?'Editando '+r.registration+'.':'Solo datos inventados. Este laboratorio no modifica la base operativa.');
 };
 const render=()=>{
  const box=$('dbdemo-list');box.replaceChildren();
  const table=document.createElement('table');table.className='dbdemo-vessels-table';const head=document.createElement('thead');
  const tr=document.createElement('tr');
  for(const label of ['Registro','Embarcación','Capitán','Etapa','Vencimiento','Acciones']){
   const th=document.createElement('th');th.textContent=label;tr.append(th);
  }head.append(tr);table.append(head);
  const body=document.createElement('tbody');
  for(const r of records){
    const row=document.createElement('tr');
    for(const [index,val] of [r.registration,r.vessel_name,r.captain,stageNames[r.stage]||r.stage,dueText(r)].entries()){
      const td=document.createElement('td');td.dataset.label=['Registro','Embarcación','Capitán','Etapa',dueLabel(r)][index];td.textContent=val;row.append(td);
    }
    const actions=document.createElement('td');actions.dataset.label='Acciones';
    const edit=document.createElement('button');edit.type='button';edit.className='secondary';edit.textContent='Editar';edit.onclick=()=>{setRecord(r);$('dbdemo-form').scrollIntoView({behavior:'smooth'});};
    const del=document.createElement('button');del.type='button';del.className='secondary';del.textContent='Eliminar';del.style.marginLeft='6px';
    del.onclick=async()=>{
      if(!confirm('¿Enviar '+r.registration+' a eliminados recuperables? No se borrarán sus movimientos.'))return;
      try{await api('/api/demo/vessels/'+r.id,'DELETE',{version:r.version});status('Registro archivado. Puedes restaurarlo desde Eliminados.');await window.servamarDemoRefresh();}catch(e){status(e.message,true);}
    };
    actions.append(edit,del);row.append(actions);body.append(row);
  }
  table.append(body);box.append(table);
  const fold=document.createElement('details');fold.className='detail-fold';
  const heading=document.createElement('summary');heading.textContent='Eliminados recuperables ('+deletedRecords.length+')';fold.append(heading);
  if(deletedRecords.length){
   const deletedTable=document.createElement('table');deletedTable.className='dbdemo-vessels-table';
   const tbody=document.createElement('tbody');
   for(const item of deletedRecords){
    const tr=document.createElement('tr');
    const td=document.createElement('td');td.textContent=item.registration+' — '+item.vessel_name+' — '+item.captain;td.dataset.label='Embarcación';tr.append(td);
    const action=document.createElement('td');action.dataset.label='Recuperación';
    const btn=document.createElement('button');btn.type='button';btn.className='secondary';btn.textContent='Restaurar';
    btn.onclick=async()=>{
      if(!confirm('¿Restaurar '+item.vessel_name+' y sus movimientos originales?'))return;
      try{await api('/api/demo/vessels/'+item.id+'/restore','POST',{version:item.version});status('Embarcación restaurada.');await window.servamarDemoRefresh();}catch(e){status(e.message,true);}
    };
    action.append(btn);tr.append(action);tbody.append(tr);
   }
   deletedTable.append(tbody);fold.append(deletedTable);
  }
  box.append(fold);
  $('dbdemo-count').textContent=records.length+' registro(s) guardados en PostgreSQL de prueba.';
 };
 window.servamarDemoRefresh=async()=>{
  try{const d=await api('/api/demo/vessels');records=d.items;const removed=await api('/api/demo/vessels/deleted');deletedRecords=removed.items;render();}catch(e){status(e.message,true);}
 };
 window.servamarDemoReset=()=>setRecord(null);
 window.servamarDemoEditById=async(id)=>{
   if(!records.length)await window.servamarDemoRefresh();
   let item=records.find(x=>x.id===Number(id));
   if(!item){await window.servamarDemoRefresh();item=records.find(x=>x.id===Number(id));}
   if(!item){status('No se encontró el registro ficticio.',true);return;}
   if(typeof showTab==='function')showTab('bdpruebas');
   setRecord(item);
   $('dbdemo-form').scrollIntoView({behavior:'smooth'});
 };
 window.servamarDemoSearch=async(filters)=>{
   const d=await api('/api/demo/vessels');
   const f=s=>String(s||'').toLocaleLowerCase('es');
   return d.items.filter(item=>{
     if(filters.q&&!f([item.registration,item.vessel_name,item.captain].join(' ')).includes(f(filters.q)))return false;
     if(filters.vessel_name&&!f(item.vessel_name).includes(f(filters.vessel_name)))return false;
     if(filters.registration_number&&!f(item.registration).includes(f(filters.registration_number)))return false;
     if(filters.captain&&!f(item.captain).includes(f(filters.captain)))return false;
     if(filters.entry_date&&item.entry_date!==filters.entry_date)return false;
     if(filters.entry_month&&!item.entry_date.startsWith(filters.entry_month))return false;
     if(filters.expiry_date&&item.due_date!==filters.expiry_date)return false;
     if(filters.expiry_month&&!(item.due_date||'').startsWith(filters.expiry_month))return false;
     return true;
   });
 };
 window.servamarDemoSave=async()=>{
  try{
    const obj=values();
    if(!obj.registration.startsWith('DEMO-'))throw Error('Usa números ficticios con prefijo DEMO-');
    if(editing){obj.version=editing.version;await api('/api/demo/vessels/'+editing.id,'PATCH',obj);status('Modificaciones guardadas en PostgreSQL.');}
    else{await api('/api/demo/vessels','POST',obj);status('Nuevo registro ficticio guardado en PostgreSQL.');}
    setRecord(null);await window.servamarDemoRefresh();
  }catch(e){status(e.message,true);}
 };
 window.servamarDemoMove=async()=>{
   const msg=$('dbdemo-movement-message');
   try{
     if(!editing)throw Error('Selecciona primero una embarcación ficticia.');
     const data={kind:$('dbdemo-movement-kind').value,
       event_date:iso($('dbdemo-movement-event').value),version:editing.version};
     if(!confirm('¿Registrar movimiento '+data.kind+' del '+editing.registration+'? Solo afecta el laboratorio.'))return;
     const r=await api('/api/demo/vessels/'+editing.id+'/movement','POST',data);
     msg.textContent='Movimiento guardado. Nuevo estado: '+(stageNames[r.stage]||r.stage)+' · '+dueLabel(r)+': '+dueText(r)+'.';
     const selectedId=editing.id;
     await window.servamarDemoRefresh();
     const updated=records.find(v=>v.id===selectedId);
     if(updated)setRecord(updated);
     await window.servamarDemoMovementHistory();
     msg.textContent='Movimiento registrado correctamente. '+dueLabel(r)+': '+dueText(r)+'.';
   }catch(e){msg.textContent='Error: '+e.message;}
 };
 window.servamarDemoMovementHistory=async()=>{
   const root=$('dbdemo-movement-history');root.replaceChildren();
   try{
     if(!editing)throw Error('Selecciona un registro ficticio');
     const j=await api('/api/demo/vessels/'+editing.id+'/movements');
     if(!j.items.length){root.textContent='Sin movimientos posteriores al ingreso.';return;}
     for(const m of j.items){
       const item=document.createElement('section');item.className='dbdemo-history-item';
       const p=document.createElement('p');p.className='dbdemo-history-summary';
       const nextLabel=m.stage_after==='salida'?'Cumple 90 días fuera':m.stage_after==='cierre'?'Permiso cerrado':'Vencimiento';
       p.textContent=fmt(m.event_date)+' · '+(movementNames[m.kind]||m.kind)+' · '+(stageNames[m.stage_before]||m.stage_before)+' → '+(stageNames[m.stage_after]||m.stage_after)+' · '+nextLabel+': '+fmt(m.due_after);
       item.append(p);
       const edit=document.createElement('button');
       edit.type='button';edit.className='secondary';edit.textContent='Corregir';
       edit.onclick=()=>{
         const existing=item.querySelector('.dbdemo-correction-form');
         if(existing){existing.remove();return;}
         const form=document.createElement('form');form.className='dbdemo-correction-form';
         const kindLabel=document.createElement('label');kindLabel.textContent='Tipo de movimiento';
         const select=document.createElement('select');select.required=true;
         for(const [value,label] of Object.entries(movementNames)){
           const option=document.createElement('option');option.value=value;option.textContent=label;select.append(option);
         }
         select.value=m.kind;kindLabel.append(select);
         const dateLabel=document.createElement('label');dateLabel.textContent='Fecha del movimiento (dd/mm/yyyy)';
         const dateInput=document.createElement('input');dateInput.type='text';dateInput.inputMode='numeric';
         dateInput.placeholder='dd/mm/yyyy';dateInput.maxLength=10;dateInput.required=true;dateInput.value=fmt(m.event_date);
         dateLabel.append(dateInput);
         const actions=document.createElement('div');actions.className='dbdemo-correction-actions';
         const save=document.createElement('button');save.type='submit';save.textContent='Guardar corrección';
         const cancel=document.createElement('button');cancel.type='button';cancel.className='secondary';cancel.textContent='Cancelar';
         cancel.onclick=()=>form.remove();actions.append(save,cancel);
         const error=document.createElement('p');error.className='dbdemo-correction-error';error.setAttribute('role','alert');
         form.append(kindLabel,dateLabel,actions,error);
         form.onsubmit=async event=>{
           event.preventDefault();error.textContent='';
           try{
             const payload={version:editing.version,kind:select.value,event_date:iso(dateInput.value)};
             if(!confirm('¿Guardar la corrección y recalcular los movimientos posteriores?'))return;
             save.disabled=true;
             const selectedId=editing.id;
             await api('/api/demo/vessels/'+selectedId+'/movements/'+m.id,'PATCH',payload);
             await window.servamarDemoRefresh();
             const updated=records.find(x=>x.id===selectedId);
             if(updated)setRecord(updated);
             await window.servamarDemoMovementHistory();
             status('Movimiento corregido; historial y vencimientos recalculados.');
           }catch(e){error.textContent=e.message;save.disabled=false;}
         };
         item.append(form);
         select.focus();
       };
       const del=document.createElement('button');
       del.type='button';del.className='secondary';del.textContent='Eliminar movimiento';
       del.style.marginLeft='6px';
       del.onclick=async()=>{
         if(!confirm('¿Eliminar este movimiento ficticio y recalcular los posteriores? La auditoría conservará el cambio.'))return;
         try{
           const selectedId=editing.id;
           await api('/api/demo/vessels/'+selectedId+'/movements/'+m.id,'DELETE',{version:editing.version});
           await window.servamarDemoRefresh();
           const updated=records.find(x=>x.id===selectedId);
           if(updated)setRecord(updated);
           await window.servamarDemoMovementHistory();
           status('Movimiento eliminado y vencimientos recalculados.');
         }catch(e){status(e.message,true);}
       };
       const controls=document.createElement('div');controls.className='dbdemo-history-actions';controls.append(edit,del);item.append(controls);root.append(item);
     }
   }catch(e){root.textContent=e.message;}
 };
 window.servamarDemoAudit=async()=>{
  const target=$('dbdemo-audit');target.replaceChildren();
  try{
   const d=await api('/api/demo/audit');
   if(!d.items.length){target.textContent='Sin modificaciones registradas.';return;}
   for(const x of d.items){
    const p=document.createElement('p');p.textContent=fmt(x.at.slice(0,10))+' '+x.at.slice(11,16)+' · '+x.action+' · '+x.registration;target.append(p);
   }
  }catch(e){target.textContent=e.message;}
 };
 window.servamarDemoDownload=async(format)=>{
  const status=document.getElementById('dbdemo-export-status');
  if(!status)return;
  status.textContent='Generando reporte de PostgreSQL DEMO...';
  try{
    const period=document.getElementById('report-period').value;
    const field=document.getElementById('report-field').value;
    const query=new URLSearchParams({format,period,field});
    if(period==='custom'){
      query.set('from',iso(document.getElementById('report-from').value));
      query.set('to',iso(document.getElementById('report-to').value));
    }
    const response=await fetch('/api/demo/export?'+query.toString(),{credentials:'same-origin'});
    if(!response.ok){
      const result=await response.json().catch(()=>({error:'Error HTTP '+response.status}));
      throw Error(result.error||'No fue posible crear el reporte');
    }
    const blob=await response.blob(),url=URL.createObjectURL(blob);
    const a=document.createElement('a');
    a.href=url;a.download='SERVAMAR_DEMO_Control.'+format;
    document.body.append(a);a.click();a.remove();
    setTimeout(()=>URL.revokeObjectURL(url),60000);
    status.textContent='Reporte PostgreSQL DEMO generado. Solo contiene datos ficticios.';
  }catch(e){status.textContent='Error: '+e.message;}
 };
 window.servamarDemoBackupStatus=async()=>{
  const element=document.getElementById('dbdemo-backup-status');
  if(!element)return;
  element.textContent='Consultando las tablas de prueba...';
  try{
    const r=await api('/api/demo/backup/status');
    element.textContent='Respaldo disponible: '+r.counts.vessels+' embarcaciones ficticias, '+
      r.counts.movements+' movimientos y '+r.counts.audit+' registros de auditoría. '+
      'No contiene datos operativos ni claves push.';
  }catch(e){element.textContent='No se pudo verificar el respaldo: '+e.message;}
 };
 window.servamarDemoInit=()=>{setRecord(null);window.servamarDemoRefresh();};
})();