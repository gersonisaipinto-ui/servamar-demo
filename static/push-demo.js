(function(){
 const status=(msg)=>{const e=document.getElementById('webpush-status');if(e)e.textContent=msg;};
 async function post(path,payload){
  const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify(payload)});
  const j=await r.json();if(!r.ok)throw Error(j.error||('Error '+r.status));return j;
 }
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
 window.servamarDisableWebPush=async()=>{
  try{
   const reg=await navigator.serviceWorker.getRegistration('/');
   const sub=reg&&await reg.pushManager.getSubscription();
   if(sub){await post('/api/push/unsubscribe',{endpoint:sub.endpoint});await sub.unsubscribe();}
   status('Avisos desactivados en este navegador.');
  }catch(e){status('Error al desactivar: '+e.message);}
 };
})();
