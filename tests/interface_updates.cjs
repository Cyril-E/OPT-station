// Release notes are available to inventory viewers and always rendered as text.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '../openprinttag_app/static');
const markup = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const catalogSource = fs.readFileSync(path.join(root, 'translations.js'), 'utf8').split('Object.freeze(')[1];
const catalog = JSON.parse(catalogSource.slice(0, catalogSource.lastIndexOf(');')));
const elements = new Map();
class Element {
  constructor(id) { this.id = id; this.hidden = false; this.open = false; this.events = {}; this.textContent = ''; }
  addEventListener(name, callback) { this.events[name] = callback; }
  removeAttribute(name) { delete this[name]; }
  showModal() { this.open = true; this.opens = (this.opens || 0) + 1; }
  close() { this.open = false; }
  click() { this.events.click?.(); }
  set innerHTML(_) { throw Error('Release notes must never be inserted as HTML'); }
}
for (const [, id] of markup.matchAll(/\bid="([^"]+)"/g)) elements.set(id, new Element(id));
let language = 'fr', fetches = 0, reloads = 0;
const answers = [], calls = [], timers = [], saved = new Map();
const events = {};
const document = {
  getElementById(id) { assert.ok(elements.has(id), `Missing HTML element: ${id}`); return elements.get(id); },
  addEventListener(name, callback) { events[name] = callback; }
};
const window = {location:{reload(){reloads++;}}, OPT_I18N: {
  init() {}, locale: () => language === 'en' ? 'en-GB' : 'fr-FR',
  msg(value, ...args) { return (language === 'en' ? catalog[value] ?? value : value).replace(/\{(\d+)\}/g, (_, i) => args[i]); },
  message: value => value,
  text(element, value) { element.textContent = value; }
}};
vm.runInNewContext(fs.readFileSync(path.join(root, 'updates.js'), 'utf8'), {
  window, document, Date, Boolean,
  AbortSignal, setTimeout(callback) { timers.push(callback); return timers.length; },
  sessionStorage:{getItem:key=>saved.get(key),setItem:(key,value)=>saved.set(key,value),removeItem:key=>saved.delete(key)},
  fetch(url, options) {
    fetches++; calls.push({url, options});
    if (!answers.length) throw Error('Opening release notes must not require full access or another request');
    const answer = answers.shift();
    return answer instanceof Error ? Promise.reject(answer) : Promise.resolve({ok:true,json:async()=>answer});
  }
});
const get = id => elements.get('updates-' + id);
const emit = updates => events['opt-station-status']({detail: {access: false, updates}});
assert.equal(get('banner').hidden, true);
assert.equal(get('notes-open').hidden, true);
const notes = '## Nouveautés\n- Sans mot de passe\n<img src=x onerror=alert(1)>\nConfiguration';
const latest = {tag: 'v999.0.0', name: 'OPT Station v999.0.0', notes, url: 'https://github.com/Cyril-E/OPT-station/releases/tag/v999.0.0'};
const status = {enabled: true, update_available: true, installed_version: '0.17.1', phase: 'ok', latest};
emit(status);
assert.equal(get('banner').hidden, false);
assert.equal(get('notes-open').hidden, false);
assert.equal(get('notes-content').textContent, notes);
assert.equal(get('fields').disabled, true);
for (const id of ['sidebar', 'banner-notes', 'notes-open']) {
  get(id).click();
  assert.equal(get('notes-dialog').open, true);
  assert.equal(get('notes-link').href, latest.url);
  get(id).click();
  assert.equal(get('notes-dialog').opens, ['sidebar', 'banner-notes', 'notes-open'].indexOf(id) + 1);
  get('notes-dialog').close();
}
language = 'en'; events['opt-station-language']();
assert.equal(get('notes-content').textContent, notes); // Do not translate publisher content.
emit({...status, latest: {...latest, notes: ''}, update_available: false});
assert.equal(get('banner').hidden, true);
assert.equal(get('notes-open').hidden, false); // Current-version notes remain accessible.
assert.equal(get('notes-content').textContent, catalog['Aucun détail n’a été fourni pour cette version. Consultez sa page GitHub.']);
get('notes-open').click();
emit({...status, error_code: 'network', message: 'Offline', stale: true});
assert.equal(get('notes-content').textContent, notes);
assert.equal(get('notes-dialog').open, true);
emit(null);
assert.equal(get('notes-dialog').open, false);
assert.equal(get('notes-link').href, undefined);
assert.equal(fetches, 0);
console.log('Release notes: inventory access, all entry points, plain text, languages, missing notes, offline state and disabled access verified.');

(async () => {
  const installation = {supported:true,phase:'idle',pending:false,percent:0,message:'Ready'};
  const offered = {...status, repository:'Cyril-E/OPT-station',revision:4,installation};
  events['opt-station-status']({detail:{access:false,updates:offered}});
  assert.equal(get('install').disabled,true);
  await get('install').events.click(); assert.equal(fetches,0);
  events['opt-station-status']({detail:{access:true,updates:offered}});
  assert.equal(get('install').disabled,false);
  const running = {...installation,id:'fixture-job',tag:latest.tag,pending:true,phase:'queued'};
  answers.push(running);
  await get('banner-install').events.click();
  assert.equal(calls[0].url,'/api/updates/install');
  assert.equal(calls[0].options.method,'POST');
  assert.deepEqual(JSON.parse(calls[0].options.body),{revision:4,tag:latest.tag});
  assert.equal(get('install').disabled,true);
  await get('install').events.click(); assert.equal(fetches,1);
  assert.equal(elements.get('update-install-progress').hidden,false);
  answers.push(new TypeError('The server is restarting'));
  await timers.shift()();
  assert.match(elements.get('update-install-message').textContent,/reconnect|reconnectera/);
  const complete = {...running,phase:'complete',pending:false,percent:100,message:'Complete'};
  answers.push({station_access:true,updates:{...offered,installed_version:'999.0.0',update_available:false,installation:complete}});
  await timers.shift()();
  assert.equal(reloads,1);
  assert.equal(saved.has('opt-station-update'),false);
  assert.equal(calls.filter(call=>call.options.method==='POST').length,1);
  assert.equal(get('install').hidden,true);
  assert.equal(timers.length,0);
  console.log('In-app installation: access, one click, duplicate prevention, restart outage, polling and automatic reload verified.');
})().catch(error=>{console.error(error);process.exitCode=1;});
