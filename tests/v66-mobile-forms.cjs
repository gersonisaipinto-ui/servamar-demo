const assert=require('node:assert/strict'),fs=require('node:fs');
const css=fs.readFileSync('static/style.css','utf8');
const html=fs.readFileSync('templates/index.html','utf8');
const app=fs.readFileSync('app.py','utf8');
for(const selector of ['#tab-nuevo .actions','#tab-buscar .actions','#tab-exportar .actions','#tab-excel .actions','#tab-avisos .actions','#tab-bdpruebas .actions','#detail .toolbar','#detail .detail-fold','#dbdemo-movement-panel .actions']){
 assert.ok(css.includes(selector),'Missing responsive selector: '+selector);
}
assert.match(css,/@media\(max-width:650px\)/);
assert.match(css, /min-height:46px/);
assert.match(css, /grid-template-columns:minmax\(0,1fr\)/);
assert.match(html,/style\.css\?v=(?:66|70)/);
assert.match(app,/VERSION='(?:6[6-9]|70)'/);
console.log('V66 mobile forms and details checks passed');
