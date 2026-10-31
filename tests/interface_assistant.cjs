// Controlled UI: explicit analysis, proposals, access loss, no stock/NFC writes.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.join(__dirname, '../openprinttag_app/static');
const markup = fs.readFileSync(path.join(root, 'index.html'),'utf8');
class Element {
  constructor() { this.events={}; this.children=[]; this.hidden=false; this.open=false; this.value=''; this.files=[]; }
  addEventListener(name,fn) { this.events[name]=fn; }
  async emit(name,event={}) { return this.events[name]?.(event); }
  append(...values) { this.children.push(...values); }
  replaceChildren(...values) { this.children=values; }
  removeAttribute(name) { delete this[name]; }
  showModal() { this.open=true; }
  close() { this.open=false; this.emit('close'); }
  set innerHTML(_) { throw Error('Untrusted text must never be inserted as HTML'); }
}
const elements=new Map([...markup.matchAll(/\bid="([^"]+)"/g)].map(([,id])=>[id,new Element()]));
const events={},dispatched=[],requests=[];
const document={getElementById(id) { assert.ok(elements.has(id),id);return elements.get(id); },
  createElement:()=>new Element(),addEventListener:(type,fn)=>events[type]=fn,
  dispatchEvent:event=>dispatched.push(event)};
const get=name=>elements.get('ai-'+name);
const settings={revision:0,enabled:true,key_saved:true,model:'gpt-5.4-mini',web_search:true};
const suggestion={main:{brand_name:'<img src=x onerror=alert(1)>',filament_diameter:1.75},title:'Label',visible_text:'Label',warnings:[],
  fields:[{field:'brand_name',value:'<img src=x onerror=alert(1)>',origin:'label',evidence:'Printed brand'}],sources:[]};
let resolveAnalysis=null;
const tick=()=>new Promise(resolve=>setImmediate(resolve));
class FileReader {
  readAsDataURL() { this.result='data:image/png;base64,AA==';this.onload(); }
}
const context={document,window:{OPT_I18N:{init(){},msg:value=>value,message:value=>value,getLanguage:()=> 'fr',text:(el,value)=>el.textContent=value}},
  FileReader,URL:{createObjectURL:()=> 'blob:test-label',revokeObjectURL(){}},AbortSignal:{timeout:()=>undefined},
  CustomEvent:class{constructor(type,data){this.type=type;this.detail=data.detail;}},setTimeout,clearTimeout,console,
  async fetch(url,options) {
    requests.push({url,options});
    if(url==='/api/configuration/assistant')return {ok:true,json:async()=>settings};
    if(url==='/api/assistant/chatgpt/signin')return {ok:true,json:async()=>({pending:null})};
    if(url==='/api/assistant/analyse')return new Promise(resolve=>{resolveAnalysis=()=>resolve({ok:true,json:async()=>suggestion});});
    throw Error('Unexpected operation: '+url);
  }};
vm.runInNewContext(fs.readFileSync(path.join(root,'assistant.js'),'utf8'),context);
(async()=>{
  assert.equal(get('open-read').disabled,true);
  events['opt-station-status']({detail:{access:true,camera:{available:true},assistant:{revision:0}}});await tick();
  assert.equal(get('open-read').disabled,false);
  await get('open-read').emit('click');await tick();
  assert.equal(get('dialog').open,true);assert.equal(get('analyse').disabled,true);
  get('file').files=[{type:'image/png',size:100}];await get('file').emit('change');
  assert.equal(get('analyse').disabled,false);
  assert.equal(requests.filter(r=>r.url.endsWith('/analyse')).length,0);
  const analysis=get('analyse').emit('click');assert.equal(get('apply').disabled,true);await tick();
  resolveAnalysis();await analysis;
  assert.equal(get('proposal').hidden,false);assert.equal(dispatched.length,0);
  assert.equal(get('proposal-fields').children[0].children[1].textContent,suggestion.fields[0].value);
  await get('apply').emit('click');
  assert.equal(dispatched[0].type,'opt-station-ai-apply');assert.equal(dispatched[0].detail.main.brand_name,suggestion.main.brand_name);
  assert.equal(get('dialog').open,false);
  await get('open-read').emit('click');await tick();
  get('file').files=[{type:'image/png',size:100}];await get('file').emit('change');
  const pending=get('analyse').emit('click');await tick();
  get('key').value='sk-FICTITIOUS_DRAFT';
  events['opt-station-status']({detail:{access:false,camera:{available:true}}});
  assert.equal(get('dialog').open,false);assert.equal(get('key').value,'');
  resolveAnalysis();await pending;
  assert.equal(dispatched.length,1);assert.equal(get('apply').disabled,true);
  assert.ok(requests.every(r=>!/(inventory|reader|favorites)/.test(r.url)));
  console.log('AI UI: explicit analysis, proposal review, plain text, form handoff, access loss and no hardware/inventory writes verified.');
})().catch(error=>{console.error(error);process.exitCode=1;});
