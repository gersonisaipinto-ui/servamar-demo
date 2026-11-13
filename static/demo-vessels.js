(function(){
 'use strict';
 let records=[],editing=null;
 const $=id=>document.getElementById(id);
 const status=(t,error=false)=>{const el=$('dbdemo-status');if(el){el.textContent=t;el.style.color=error?'#9b2121':'';}};
 const fmt=d=>{const m=/^(\d{4})-(\d{2})-(\d{2})$/.exec(String(d||''));return m?m[3]+'/'+m[2]+'/'+m[1]:(d||'—');};
 const iso=d=>{const m=/^(\d{2})\/(\d{2})\/(\d{4})$/.exec(String(d||'').trim());if(!m)throw Error('Escribe fechas como dd/mm/yyyy');const x=m[3]+'-'+m[2]+'-'+m[1];const q=new Date(x+'T12:00:00Z');if(Number.isNaN(q.getTime())||q.toISOString().slice(0,10)!==x)throw Error('Fecha inválida: '+d);return x;};
 const api=async(path,method='GET',payload)=>{
   const r=await fetch(path,{method,credentials:'same-origin',headers:{'Accept':'application/json','Content-Type':'application/json'},...(payload?{body:JSON.stringify(payload)}:{})});
   const j=await r.json();if(!r.ok)throw Error(j.error||('Error '+r.status));return j;
 };
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
  status(r?'Editando '+r.registration+'.':'Solo datos inventados. Este laboratorio no modifica la base operativa.');
 };
 const render=()=>{
  const box=$('dbdemo-list');box.replaceChildren();
  const table=document.createElement('table');const head=document.createElement('thead');
  const tr=document.createElement('tr');
  for(const label of ['Registro','Embarcación','Capitán','Etapa','Vencimiento','Acciones']){
   const th=document.createElement('th');th.textContent=label;tr.append(th);
  }head.append(tr);table.append(head);
  const body=document.createElement('tbody');
  for(const r of records){
    const row=document.createElement('tr');
    for(const val of [r.registration,r.vessel_name,r.captain,r.stage,fmt(r.due_date)]){
      const td=document.createElement('td');td.textContent=val;row.append(td);
    }
    const actions=document.createElement('td');
    const edit=document.createElement('button');edit.type='button';edit.className='secondary';edit.textContent='Editar';edit.onclick=()=>{setRecord(r);$('dbdemo-form').scrollIntoView({behavior:'smooth'});};
    const del=document.createElement('button');del.type='button';del.className='secondary';del.textContent='Eliminar';del.style.marginLeft='6px';
    del.onclick=async()=>{
      if(!confirm('¿Eliminar '+r.registration+'? Esta acción solo afecta al laboratorio ficticio.'))return;
      try{await api('/api/demo/vessels/'+r.id,'DELETE',{version:r.version});status('Eliminación registrada.');await window.servamarDemoRefresh();}catch(e){status(e.message,true);}
    };
    actions.append(edit,del);row.append(actions);body.append(row);
  }
  table.append(body);box.append(table);
  $('dbdemo-count').textContent=records.length+' registro(s) guardados en PostgreSQL de prueba.';
 };
 window.servamarDemoRefresh=async()=>{
  try{const d=await api('/api/demo/vessels');records=d.items;render();}catch(e){status(e.message,true);}
 };
 window.servamarDemoReset=()=>setRecord(null);
 window.servamarDemoSave=async()=>{
  try{
    const obj=values();
    if(!obj.registration.startsWith('DEMO-'))throw Error('Usa números ficticios con prefijo DEMO-');
    if(editing){obj.version=editing.version;await api('/api/demo/vessels/'+editing.id,'PATCH',obj);status('Modificaciones guardadas en PostgreSQL.');}
    else{await api('/api/demo/vessels','POST',obj);status('Nuevo registro ficticio guardado en PostgreSQL.');}
    setRecord(null);await window.servamarDemoRefresh();
  }catch(e){status(e.message,true);}
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
 window.servamarDemoInit=()=>{setRecord(null);window.servamarDemoRefresh();};
})();