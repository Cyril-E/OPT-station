// ChatGPT setup: explicit provider choice, OAuth handoff, model choice and no implicit billing switch.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
class Element{
 constructor(){this.events={};this.children=[];this.hidden=false;this.open=false;this.value='';this.files=[];}
 addEventListener(k,fn){this.events[k]=fn;}emit(k,e={}){return this.events[k]?.(e);}append(...v){this.children.push(...v);}replaceChildren(...v){this.children=v;}
 removeAttribute(k){delete this[k];}showModal(){this.open=true;}close(){this.open=false;this.emit('close');}set innerHTML(_){throw Error('Untrusted HTML');}
}
const root=path.join(__dirname,'../openprinttag_app/static'),html=fs.readFileSync(path.join(root,'index.html'),'utf8');
const elements=new Map([...html.matchAll(/\bid="([^"]+)"/g)].map(([,id])=>[id,new Element()]));const get=k=>elements.get('ai-'+k);
let connection={revision:0,active:null,profiles:[],models:[],connected:false,plan_enabled:false};
let config={revision:0,enabled:true,key_saved:true,ready:true,model:'gpt-5.4-mini',web_search:true,provider:'api',chatgpt_model:'',chatgpt:connection};
const events={},requests=[],popup={opener:{},location:{},close(){this.closed=true;}};let nextStatus='pending',activeAttempt=null,throwNextPoll=false;
const timers=new Map();let nextTimer=0;
const context={document:{getElementById:id=>elements.get(id),createElement:()=>new Element(),addEventListener:(type,fn)=>events[type]=fn},
 window:{open:()=>popup,OPT_I18N:{init(){},msg:s=>s,message:s=>s,text:(el,v)=>el.textContent=v}},
 setTimeout(fn){timers.set(++nextTimer,fn);return nextTimer;},clearTimeout(id){timers.delete(id);},AbortSignal:{timeout:()=>undefined},
 async fetch(url,options){const body=options.body?JSON.parse(options.body):null;requests.push({url,body,method:options.method});let value;
  if(url==='/api/configuration/assistant'){
   if(body)config={...config,...body,revision:config.revision+1};value={...config,chatgpt:connection};
  }else if(url==='/api/assistant/chatgpt/signin'){
   if(options.method==='GET')value={pending:activeAttempt};
   else{activeAttempt={attempt_id:'fixture-attempt',authorization_url:'https://auth.openai.com/fixture',callback_uri:'http://127.0.0.1:1234/auth/callback'};value=activeAttempt;}
  }else if(url.endsWith('/return')){activeAttempt=null;connection={revision:1,active:'profile-one',profiles:[{id:'profile-one',label:'<img src=x> · 1'}],models:[],connected:true,plan_enabled:true};value=connection;}
  else if(url.endsWith('/models')){connection={...connection,revision:connection.revision+1,models:[{slug:'vision-fixture',display_name:'Vision fixture'}]};value={items:connection.models};}
  else if(url.endsWith('/fixture-attempt')){
   if(options.method==='DELETE'){activeAttempt=null;value={cancelled:true};}
   else{if(throwNextPoll){throwNextPoll=false;throw Error('Controlled timeout');}value={status:nextStatus,connection};}
  }
  else throw Error('Unexpected request '+url);
  return {ok:true,json:async()=>value};
 }};
vm.runInNewContext(fs.readFileSync(path.join(root,'assistant.js'),'utf8'),context);
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 events['opt-station-status']({detail:{access:true,camera:{available:true},assistant:{revision:0}}});await tick();
 assert.equal(get('provider').value,'api');assert.equal(get('chatgpt-fields').hidden,true);
 get('provider').value='chatgpt';await get('settings-form').emit('input');await get('provider').emit('change');
 assert.equal(get('api-fields').hidden,true);assert.equal(config.provider,'api');
 await get('chatgpt-connect').emit('click');assert.equal(popup.location.href,'https://auth.openai.com/fixture');assert.equal(get('chatgpt-pending').hidden,false);
 assert.equal(requests.some(x=>x.url.includes('/analyse')),false);
 get('chatgpt-return').value='http://127.0.0.1:1234/auth/callback?code=fixture&state=fixture';await get('chatgpt-return').emit('input');
 await get('chatgpt-finish').emit('click');assert.equal(get('chatgpt-return').value,'');assert.equal(get('chatgpt-pending').hidden,true);
 assert.equal(get('chatgpt-account').children[0].textContent,'<img src=x> · 1');
 assert.equal(config.provider,'api');assert.equal(get('provider').value,'chatgpt');
 get('chatgpt-model').value='vision-fixture';await get('settings-form').emit('input');await get('settings-form').emit('submit',{preventDefault(){}});
 assert.equal(config.provider,'chatgpt');assert.equal(config.chatgpt_model,'vision-fixture');assert.equal(config.api_key,null);
 assert.equal(get('key').value,'');
 await get('chatgpt-connect').emit('click');events['opt-station-status']({detail:{access:false,camera:{available:true}}});
 assert.equal(get('chatgpt-open').href,undefined);assert.equal(get('chatgpt-return').value,'');assert.equal(get('chatgpt-pending').hidden,true);
 // A fresh page recovers the server-side attempt without local/session storage or a second registration.
 const starts=requests.filter(r=>r.url==='/api/assistant/chatgpt/signin'&&r.method==='POST').length;
 for(const id of elements.keys())elements.set(id,new Element());
 vm.runInNewContext(fs.readFileSync(path.join(root,'assistant.js'),'utf8'),context);
 events['opt-station-status']({detail:{access:true,camera:{available:true},assistant:{revision:config.revision}}});await tick();
 assert.equal(get('chatgpt-pending').hidden,false);assert.equal(get('chatgpt-open').href,activeAttempt.authorization_url);
 assert.equal(get('chatgpt-connect').disabled,true);assert.equal(get('chatgpt-cancel').disabled,false);
 assert.equal(requests.filter(r=>r.url==='/api/assistant/chatgpt/signin'&&r.method==='POST').length,starts);
 get('chatgpt-return').value='fixture-callback-draft';throwNextPoll=true;
 const beforeDelete=requests.filter(r=>r.method==='DELETE').length;
 const [timer,run]=timers.entries().next().value;timers.delete(timer);await run();await tick();
 assert.equal(get('chatgpt-pending').hidden,false);assert.equal(get('chatgpt-return').value,'fixture-callback-draft');
 assert.equal(requests.filter(r=>r.method==='DELETE').length,beforeDelete);assert.equal(timers.size,1);
 await get('chatgpt-cancel').emit('click');assert.equal(activeAttempt,null);assert.equal(get('chatgpt-pending').hidden,true);assert.equal(timers.size,0);
 console.log('ChatGPT UI: explicit billing, handoff recovery after reload, transient-network retry without cancellation, callback clearing, model choice and access loss verified.');
})().catch(error=>{console.error(error);process.exitCode=1;});
