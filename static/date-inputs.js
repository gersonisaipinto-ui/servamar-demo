/* SERVAMAR V57: fechas móviles con formato automático y calendario nativo.
   Este módulo nunca modifica fechas en la base de datos: solo la entrada visual. */
(function(){
'use strict';
const IDS = new Set(['new-entry','entrydate','expirydate','start','edit-event-date','report-from','report-to']);
function formatDigits(value){
  const digits=String(value==null?'':value).replace(/\D/g,'').slice(0,8);
  if(digits.length<=2)return digits+(digits.length===2?'/':'');
  if(digits.length<=4)return digits.slice(0,2)+'/'+digits.slice(2)+(digits.length===4?'/':'');
  return digits.slice(0,2)+'/'+digits.slice(2,4)+'/'+digits.slice(4);
}
function isoToDisplay(iso){
  const m=/^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso||''));
  return m?`${m[3]}/${m[2]}/${m[1]}`:'';
}
function displayToIso(display){
  const m=/^(\d{2})\/(\d{2})\/(\d{4})$/.exec(String(display||''));
  if(!m)return '';
  const d=Number(m[1]),month=Number(m[2]),year=Number(m[3]);
  const dt=new Date(Date.UTC(year,month-1,d));
  if(year<1900||year>2200||dt.getUTCFullYear()!==year||dt.getUTCMonth()!==month-1||dt.getUTCDate()!==d)return '';
  return `${m[3]}-${m[2]}-${m[1]}`;
}
function decorate(input){
  if(!input || input.dataset.servamarDateReady==='1')return;
  input.dataset.servamarDateReady='1';
  input.type='text'; input.inputMode='numeric'; input.autocomplete='off'; input.maxLength=10;
  input.placeholder='dd/mm/aaaa';
  const wrap=document.createElement('span');wrap.className='servamar-date-wrap';
  input.parentNode.insertBefore(wrap,input);wrap.appendChild(input);
  const picker=document.createElement('input');picker.type='date';
  picker.className='servamar-native-date';picker.tabIndex=-1;picker.setAttribute('aria-label','Elegir fecha del calendario');
  picker.min='1900-01-01';picker.max='2200-12-31';
  const button=document.createElement('button');button.type='button';button.className='servamar-calendar-btn';
  button.textContent='📅';button.title='Elegir fecha en el calendario';button.setAttribute('aria-label','Abrir calendario');
  wrap.appendChild(button);wrap.appendChild(picker);
  function syncPicker(){picker.value=displayToIso(input.value)}
  input.addEventListener('input',function(){
    const old=this.value; const wasAtEnd=this.selectionStart===old.length;
    const updated=formatDigits(old);
    if(updated!==old){this.value=updated;if(wasAtEnd){try{this.setSelectionRange(updated.length,updated.length)}catch(e){}}}
    syncPicker();
  });
  input.addEventListener('keydown',function(e){
    if(e.key==='Backspace' && this.selectionStart===this.selectionEnd && this.selectionStart===this.value.length && this.value.endsWith('/')){
      e.preventDefault();this.value=formatDigits(this.value.replace(/\D/g,'').slice(0,-1));
      this.dispatchEvent(new Event('input',{bubbles:true}));
    }
  });
  input.addEventListener('change',syncPicker);
  picker.addEventListener('change',function(){
    if(!this.value)return;
    input.value=isoToDisplay(this.value);
    input.dispatchEvent(new Event('input',{bubbles:true}));
    input.dispatchEvent(new Event('change',{bubbles:true}));
  });
  button.addEventListener('click',function(){
    syncPicker();
    try { if(typeof picker.showPicker==='function')picker.showPicker();else {picker.focus();picker.click();} }
    catch(e){picker.focus();picker.click()}
  });
  syncPicker();
}
function scan(root){
  if(!root)return;
  if(root.nodeType===1&&IDS.has(root.id))decorate(root);
  if(root.querySelectorAll)root.querySelectorAll('input[id]').forEach(el=>{if(IDS.has(el.id))decorate(el)});
}
function init(){scan(document);new MutationObserver(records=>{for(const r of records)for(const node of r.addedNodes)scan(node)}).observe(document.body,{childList:true,subtree:true})}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
window.SERVAMARDateInputs={formatDigits,displayToIso,isoToDisplay};
})();
