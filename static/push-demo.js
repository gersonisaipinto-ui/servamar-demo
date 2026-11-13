(function(){
 const status=(msg)=>{const e=document.getElementById('webpush-status');if(e)e.textContent=msg;};
 async function post(path,payload){
  const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify(payload)});
  const j=await r.json();if(!r.ok)throw Error(j.error||('Error '+r.status));return j;
 }
 const formatDate=s=>{
   const m=/^(\d{4})-(\d{2})-(\d{2})$/.exec(String(s||''));
   return m?m[3]+'/'+m[2]+'/'+m[1]:(s||'—');
 };
 const formatDateTime=s=>{
   const m=/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(String(s||''));
   return m?m[3]+'/'+m[2]+'/'+m[1]+' '+m[4]+':'+m[5]:(s||'—');
 };
 const keyBytes=s=>{const txt=atob((s+'='.repeat((4-s.length%4)%4)).replace(/-/g,'+').replace(/_/g,'/'));return Uint8Array.from(txt,c=>c.charCodeAt(0));};
 window.servamarEnableWebPush=async()=>{
  try{
   if(!isSecureContext||!('serviceWorker'in navigator)||!('PushManager'in window)||!('Notification'in window))throw Error('Este navegador no admite Web Push');
   if(await Notification.requestPermission()!=='granted')throw Error('No has autorizado las notificaciones');
   const reg=await navigator.serviceWorker.register('/push-sw.js',{scope:'/'});
   const resp=await fetch('/api/push/public-key',{credentials:'same-origin'});
   if(!resp.ok)throw Error('Error obteniendo la clave pública');
   const data=await resp.json();
   let sub=await reg.pushManager.getSubscription();
   if(sub){await sub.unsubscribe();sub=null;}
   sub=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:keyBytes(data.publicKey)});
   await post('/api/push/subscribe',sub.toJSON());
   status(data.ephemeral
     ? 'Avisos activados en modo temporal. Después de reiniciar Render debes activarlos nuevamente.'
     : 'Avisos activados con almacenamiento PostgreSQL. Suscripción guardada en la base de prueba.');
  }catch(e){status('No se pudo activar: '+e.message);}
 };
 window.servamarTestWebPush=async()=>{
  try{
   const j=await post('/api/push/test',{});
   status(j.message+' Dispositivos registrados: '+j.subscribers+'.');
  }catch(e){status('Error en prueba: '+e.message);}
 };
 const get=async path=>{
   const r=await fetch(path,{credentials:'same-origin'});
   const j=await r.json();
   if(!r.ok)throw Error(j.error||('HTTP '+r.status));
   return j;
 };
 const line=(parent,message)=>{
   const p=document.createElement('p');
   p.textContent=message;
   parent.appendChild(p);
 };
 window.servamarLoadPushSchedule=async()=>{
   const root=document.getElementById('webpush-schedule');
   if(!root)return;
   root.replaceChildren();
   line(root,'Consultando próximos recordatorios ficticios...');
   try{
     const d=await get('/api/push/schedule?days=45');
     root.replaceChildren();
     line(root,'Avisos previstos entre '+formatDate(d.start)+' y '+formatDate(d.through)+': '+d.count+'.');
     if(!d.events.length)line(root,'No hay recordatorios en este periodo.');
     for(const item of d.events.slice(0,100)){
       const category=item.category==='retorno_temporal'?'Retorno temporal':'Vencimiento';
       line(root,formatDate(item.notify_on)+' · '+item.vessel+' · '+category+
         ' · '+item.days_before+' día(s) antes del '+formatDate(item.deadline));
     }
   }catch(e){root.replaceChildren();line(root,'No se pudo consultar la agenda: '+e.message);}
 };
 window.servamarLoadPushHistory=async()=>{
   const root=document.getElementById('webpush-history');
   if(!root)return;
   root.replaceChildren();
   line(root,'Consultando el historial...');
   try{
     const d=await get('/api/push/status');
     root.replaceChildren();
     line(root,'Almacenamiento: '+d.storage+' · Dispositivos inscritos: '+d.subscribers+'.');
     line(root,d.delivery_note);
     if(!d.history.length)line(root,'Todavía no hay envíos diarios registrados.');
     for(const item of d.history){
       line(root,formatDateTime(item.registered_at)+' · '+formatDate(item.date)+' · '+item.status+
         ' · '+item.alert_count+' avisos · '+item.accepted_by_provider+' aceptaciones del proveedor.');
     }
   }catch(e){root.replaceChildren();line(root,'No se pudo consultar el historial: '+e.message);}
 };
 window.servamarDisableWebPush=async()=>{
  try{
   const reg=await navigator.serviceWorker.getRegistration('/');
   const sub=reg&&await reg.pushManager.getSubscription();
   if(sub){await post('/api/push/unsubscribe',{endpoint:sub.endpoint});await sub.unsubscribe();}
   status('Avisos desactivados en este navegador.');
  }catch(e){status('Error al desactivar: '+e.message);}
 };
})();
