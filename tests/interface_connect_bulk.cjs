// Isolated browser behaviour: explicit sends, a serial queue, cancellation and truthful results.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '../openprinttag_app/static');
const markup = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const events = {}, windowEvents = {}, elements = new Map(), answers = [], calls = [], dispatched = [];
class Element {
  constructor(id) { this.id = id; this.events = {}; this.children = []; this.disabled = false; }
  addEventListener(name, callback) { this.events[name] = callback; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  showModal() { this.open = true; }
  close() { this.open = false; this.events.close?.(); }
  set innerHTML(_) { throw Error('Names and server messages must be rendered as text'); }
}
for (const [, id] of markup.matchAll(/\bid="([^"]+)"/g)) elements.set(id, new Element(id));
const get = suffix => elements.get('connect-bulk-' + suffix);
const document = {
  getElementById(id) { assert.ok(elements.has(id), `Missing element ${id}`); return elements.get(id); },
  createElement: () => new Element(),
  addEventListener(name, callback) { events[name] = callback; },
  dispatchEvent(event) { dispatched.push(event); }
};
const window = {addEventListener(name, callback) { windowEvents[name] = callback; }, OPT_I18N: {
  msg: (text, ...args) => text.replace(/\{(\d+)\}/g, (_, n) => args[n]), message: value => value,
  text: (element, value) => { element.textContent = value; }
}};
vm.runInNewContext(fs.readFileSync(path.join(root, 'connect-bulk.js'), 'utf8'), {
  window, document, AbortController, Error, TypeError, SyntaxError, setTimeout, clearTimeout,
  CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options?.detail; } },
  async fetch(url, options) {
    calls.push({url, body:JSON.parse(options.body)});
    assert.ok(answers.length, `Unexpected request: ${url}`);
    const answer = await answers.shift();
    if (answer.error) throw answer.error;
    return {ok:!answer.status || answer.status === 200, status:answer.status || 200, json:async () => answer.body};
  }
});
const tick = () => new Promise(resolve => setImmediate(resolve));
const click = async name => { get(name).events.click(); await tick(); };
const emit = access => events['opt-station-status']({detail:{access}});
const spool = (id, disposition = 'create', message) => ({id, name:'<b>' + id + '</b>', spool_number:id,
  version:3, notes_revision:2, fingerprint:'f'.repeat(64), disposition, message});
function queuePreview(items) {
  answers.push({body:{organization:'Test team', counts:{total:items.length, missing:items.filter(x => x.disposition === 'create').length,
    ready:items.filter(x => x.disposition === 'create').length, present:items.filter(x => x.disposition === 'present').length,
    blocked:items.filter(x => x.disposition === 'blocked').length}, items}});
}
const success = {body:{status:'created',created:true,verified:true,visible_in_connect:true}};

(async () => {
  await click('open'); assert.equal(calls.length, 0);
  emit(true);
  queuePreview([spool('B0000','present'), spool('B0001'), spool('B0002'), spool('B0003','blocked','Poids manquant')]);
  await click('open');
  assert.equal(get('dialog').open, true);
  assert.equal(calls.length, 1); // Preview does not send anything.
  assert.match(get('summary').textContent, /4 bobines actives/);
  assert.equal(get('items').children[1].children[0].children[0].textContent, 'B0001 · <b>B0001</b>');
  assert.match(get('items').children[3].children[0].children[0].textContent, /^B0003 · /);
  let resolve;
  answers.push(new Promise(r => { resolve = r; }), {body:{status:'already_present',created:false}});
  await click('send');
  assert.equal(calls.length, 2);
  assert.equal(get('send').disabled, true);
  await click('send'); assert.equal(calls.length, 2); // No double submission or parallel sends.
  let prevented = false;
  get('dialog').events.cancel({preventDefault() { prevented = true; }}); assert.ok(prevented);
  resolve(success); await tick(); await tick();
  assert.equal(calls.length, 3);
  assert.match(calls[1].url, /B0001\/connect\/export-missing$/);
  assert.deepEqual(calls[1].body, {version:3,notes_revision:2,fingerprint:'f'.repeat(64)});
  assert.match(get('summary').textContent, /1 envoyées · 2 déjà présentes · 1 à traiter/);
  assert.ok(get('send').hidden);
  assert.ok(dispatched.some(e => e.type === 'opt-station-inventory-updated'));
  const correction = get('items').children[3].children[1];
  correction.events.click();
  assert.equal(get('dialog').open, false);
  assert.deepEqual(dispatched.at(-1).detail.id, 'B0003');
  queuePreview([spool('B0001'), spool('B0002')]); await click('open');
  answers.push(new Promise(r => { resolve = r; })); await click('send');
  const beforeCancel = calls.length;
  await click('cancel'); resolve(success); await tick(); await tick();
  assert.equal(calls.length, beforeCancel); // Current request completes, no next request.
  assert.match(get('summary').textContent, /1 envoyées · 0 déjà présentes · 1 à traiter/);
  assert.match(get('result').textContent, /arrêté/);
  queuePreview([spool('B0001','present'),spool('B0002'),spool('B0003')]); await click('check');
  answers.push({status:409,body:{detail:'Cette fiche a changé.'}},success); await click('send');
  assert.match(get('summary').textContent, /1 envoyées · 1 déjà présentes · 1 à traiter/);
  queuePreview([spool('B0002'),spool('B0003')]); await click('check');
  answers.push({error:new TypeError('offline')}); await click('send');
  assert.match(get('items').children[0].children[0].children[2].textContent, /aucun envoi n’est relancé/);
  assert.match(get('items').children[1].children[0].children[1].textContent, /Non envoyée/);
  const afterFailure = calls.length; await click('send'); assert.equal(calls.length, afterFailure);
  queuePreview([spool('B0002'),spool('B0003')]); await click('check');
  answers.push(new Promise(r => { resolve = r; })); await click('send');
  const beforeNavigate = calls.length;
  windowEvents.pagehide(); resolve(success); await tick(); await tick(); windowEvents.pageshow();
  assert.equal(calls.length, beforeNavigate);
  assert.match(get('items').children[0].children[0].children[1].textContent, /À vérifier/);
  assert.match(get('result').textContent, /aucun envoi n’est relancé/);
  assert.equal(get('check').disabled, false);
  queuePreview([spool('B0002')]); await click('check');
  answers.push(new Promise(r => { resolve = r; })); await click('send');
  emit(false); resolve(success); await tick(); await tick();
  assert.equal(get('dialog').open, false);
  assert.equal(get('items').children.length, 0);
  assert.equal(get('open').disabled, true);
  emit(true); queuePreview([]); await click('open');
  assert.equal(get('send').disabled, true);
  assert.match(get('result').textContent, /Aucune bobine prête/);
  assert.equal(answers.length, 0);
  console.log('Bulk export: preview, explicit serial writes, concurrent presence, partial failure, stop, retry, access loss and safe text verified.');
})().catch(error => { console.error(error); process.exitCode = 1; });
