'use strict';
self.addEventListener('push',event=>{
 let content={};
 try{content=event.data?event.data.json():{};}catch(e){content={};}
 const title=typeof content.title==='string'?content.title.slice(0,90):'SERVAMAR - Notificación';
 const body=typeof content.body==='string'?content.body.slice(0,180):'Aviso de SERVAMAR.';
 event.waitUntil(self.registration.showNotification(title,{
  body,tag:'servamar-administrativo',data:{url:'/'}
 }));
});
self.addEventListener('notificationclick',event=>{
 event.notification.close();
 event.waitUntil(clients.matchAll({type:'window',includeUncontrolled:true}).then(w=>{
  const existing=w.find(c=>c.url.startsWith(self.location.origin+'/'));
  return existing?existing.focus():clients.openWindow('/');
 }));
});
