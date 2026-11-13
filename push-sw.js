'use strict';
self.addEventListener('push',event=>{
 event.waitUntil(self.registration.showNotification('SERVAMAR — Aviso de prueba',{
  body:'Esta es una notificación de prueba sin datos de expedientes.',
  tag:'servamar-prueba',data:{url:'/'}
 }));
});
self.addEventListener('notificationclick',event=>{
 event.notification.close();
 event.waitUntil(clients.matchAll({type:'window',includeUncontrolled:true}).then(w=>{
  const existing=w.find(c=>c.url.startsWith(self.location.origin+'/'));
  return existing?existing.focus():clients.openWindow('/');
 }));
});
