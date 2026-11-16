from html.parser import HTMLParser
from pathlib import Path
class Check(HTMLParser):
 def __init__(self):
  super().__init__();self.stack=[];self.sections={};self.current=None;self.ids=set()
 def handle_starttag(self,tag,attrs):
  attrs=dict(attrs)
  if tag=='section' and attrs.get('id','').startswith('tab-'):
   self.current=attrs['id'];self.sections[self.current]=0
  if tag=='details':
   self.stack.append((self.current,False))
   if self.current in self.sections:self.sections[self.current]+=1
  if tag=='summary' and self.stack:
   sec,flag=self.stack[-1];self.stack[-1]=(sec,True)
  if 'id' in attrs:
   assert attrs['id'] not in self.ids,'duplicate id '+attrs['id']
   self.ids.add(attrs['id'])
 def handle_endtag(self,tag):
  if tag=='details':
   assert self.stack,'unmatched details closing'
   sec,summary=self.stack.pop()
   assert summary,'details missing summary in '+str(sec)
html=Path('templates/index.html').read_text()
c=Check();c.feed(html)
assert not c.stack,'unclosed details '+str(c.stack)
for sec in ['tab-inicio','tab-nuevo','tab-buscar','tab-avisos','tab-exportar','tab-excel','tab-bdpruebas']:
 assert c.sections.get(sec,0)>=1,(sec,c.sections)
assert 'id="dbdemo-editor-fold"' in html
assert 'confirm_archive:confirmation' in Path('static/demo-vessels.js').read_text()
print('V71: balanced disclosures, unique IDs, all tabs covered')
