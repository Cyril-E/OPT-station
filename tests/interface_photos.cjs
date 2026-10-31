// Photo UI: explicit attachment, permissions, stale responses and camera cleanup.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=path.join(__dirname,'../openprinttag_app/static');
class Element{
 constructor(tag='div'){this.tag=tag;this.events={};this.children=[];this.hidden=false;this.open=false;this.value='';this.files=[];}
 addEventListener(name,fn){this.events[name]=fn;}
 emit(name,event={}){return this.events[name]?.(event);}
 append(...items){this.children.push(...items);}
 replaceChildren(...items){this.children=items;}
 removeAttribute(name){delete this[name];}
 querySelectorAll(tag){return this.children.flatMap(x=>[...(x.tag===tag?[x]:[]),...x.querySelectorAll(tag)]);}
 showModal(){this.open=true;}close(){this.open=false;this.emit('close');}focus(){}
 set innerHTML(_){throw Error('Untrusted attachment text must stay plain text');}
}
const markup=fs.readFileSync(path.join(root,'index.html'),'utf8');
const elements=new Map([...markup.matchAll(/\bid="([^"]+)"/g)].map(([,id])=>[id,new Element()]));
const get=name=>elements.get('photos-'+name),events={},requests=[],data=new Map();let pendingUpload=null,pendingCamera=null;
const response=value=>({ok:true,json:async()=>value});
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const context={document:{getElementById:id=>elements.get(id),createElement:tag=>new Element(tag),addEventListener:(name,fn)=>events[name]=fn},
 window:{OPT_I18N:{msg:(s,...v)=>s.replace(/\{(\d+)\}/g,(_,n)=>v[n]),message:s=>s,text:(el,s)=>el.textContent=s,attribute:(el,k,s)=>el[k]=s,locale:()=> 'en-GB'}},
 FileReader:class{readAsDataURL(){this.result='data:image/png;base64,AA==';this.onload();}},
 URL:{createObjectURL:()=> 'blob:fixture',revokeObjectURL(){}},AbortSignal:{timeout:()=>undefined},setTimeout,clearTimeout,
 async fetch(url,options){
  requests.push({url,options});
  assert.ok(!url.includes('/assistant')&&!url.includes('/reader')&&!url.includes('/write'));
  if(url==='/api/camera/photos')return new Promise(resolve=>pendingCamera=()=>resolve(response({id:'late-capture'})));
  if(url==='/api/camera/scans/late-capture'&&options.method==='DELETE')return response({cancelled:true});
  if(options.method==='GET')return response({items:data.get(url)||[]});
  if(options.method==='POST')return new Promise(resolve=>{pendingUpload=()=>{data.set(url,[{id:'photo-one',created_at:'2026-10-31T12:00:00Z'}]);resolve(response({id:'photo-one'}));};});
  if(options.method==='DELETE'){data.set(url.slice(0,url.lastIndexOf('/')),[]);return response({deleted:true});}
  throw Error('Unexpected request '+url);
 }};
vm.runInNewContext(fs.readFileSync(path.join(root,'photos.js'),'utf8'),context);
(async()=>{
 events['opt-station-status']({detail:{access:false,browse:true,camera:{available:true}}});
 context.window.OPT_PHOTOS.open('spool','spool-one','B0000 <img src=x>');await tick();
 assert.equal(get('camera').disabled,true);assert.equal(get('file').disabled,false);
 get('file').files=[{type:'image/png',size:100}];await get('file').emit('change');
 assert.equal(get('proposal').hidden,false);assert.equal(requests.filter(x=>x.options.method==='POST').length,0);
 const save=get('save').emit('click');await tick();assert.ok(pendingUpload);pendingUpload();await save;await tick();
 assert.equal(get('proposal').hidden,true);assert.equal(get('message').textContent,'1 photo(s) jointe(s).');
 assert.equal(get('title').textContent,'B0000 <img src=x>');
 const remove=get('gallery').querySelectorAll('button')[0];await remove.emit('click');assert.equal(get('delete-confirm').hidden,false);
 await get('delete-no').emit('click');assert.equal(requests.filter(x=>x.options.method==='DELETE').length,0);
 await remove.emit('click');await get('delete-yes').emit('click');assert.equal(get('message').textContent,'0 photo(s) jointe(s).');
 // An upload to A may finish after closing, but cannot change B's gallery.
 get('file').files=[{type:'image/png',size:100}];await get('file').emit('change');const slow=get('save').emit('click');await tick();
 get('dialog').close();context.window.OPT_PHOTOS.open('template','model-two','Model two');await tick();pendingUpload();await slow;await tick();
 assert.equal(get('title').textContent,'Model two');assert.equal(get('message').textContent,'0 photo(s) jointe(s).');
 events['opt-station-status']({detail:{access:true,browse:true,camera:{available:true}}});
 const capture=get('camera').emit('click');await tick();get('dialog').close();pendingCamera();await capture;
 assert.ok(requests.some(x=>x.url==='/api/camera/scans/late-capture'&&x.options.method==='DELETE'));
 context.window.OPT_PHOTOS.open('spool','spool-one','B0000');await tick();
 events['opt-station-status']({detail:{access:false,browse:false,camera:{available:true}}});assert.equal(get('dialog').open,false);
 console.log('Photo UI: preview before saving, inventory access, confirmation, plain text, stale upload isolation, camera cleanup and access loss verified.');
})().catch(error=>{console.error(error);process.exitCode=1;});
