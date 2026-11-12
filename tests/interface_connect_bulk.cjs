// Isolated browser behaviour: explicit sends, a serial queue, cancellation and truthful results.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '../openprinttag_app/static');
const markup = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const events = {}, windowEvents = {}, elements = new Map(), answers = [], calls = [], dispatched = [];
let now = 1000;
class Element {
  constructor(id) { this.id = id; this.events = {}; this.children = []; this.disabled = false; this.dataset = {}; }
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
  body: {dataset: {tab: 'printer'}}, hidden: false,
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
  window, document, AbortController, Error, TypeError, SyntaxError, setTimeout, clearTimeout, Date: {now: () => now},
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
  version:3, notes_revision:2, fingerprint:'f'.repeat(64), disposition, message,
  presence: disposition === 'present' ? 'present' : disposition === 'create' ? 'absent' : 'unknown'});
function queuePreview(items) {
  answers.push({body:{organization:'Test team', counts:{total:items.length, missing:items.filter(x => x.presence === 'absent').length,
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
  await click('close');

  // The inventory indicator covers all active stock, including blocked records;
  // it only reads Connect and never borrows the visible Production filter.
  document.body.dataset.tab = 'inventory';
  const indicatorStart = calls.length;
  const blockedAbsent = {...spool('B0003', 'blocked'), presence:'absent'};
  queuePreview([spool('B0000','present'), spool('B0001'), blockedAbsent, spool('B0004','blocked')]);
  events['opt-station-inventory-loaded'](); await tick();
  assert.equal(get('count').hidden, false);
  assert.equal(get('count').textContent, '2');
  assert.match(get('status').textContent, /Absentes : 2 · Prêtes à envoyer : 1 · À vérifier : 2/);
  assert.equal(get('dialog').open, false);
  assert.equal(calls.length, indicatorStart + 1);
  emit(true); await tick(); assert.equal(calls.length, indicatorStart + 1); // Throttled background reads.

  answers.push({error:new TypeError('offline')});
  events['opt-station-inventory-loaded'](); await tick();
  assert.equal(get('count').hidden, true);
  assert.match(get('status').textContent, /indisponible/);
  queuePreview([spool('B0004','blocked')]);
  events['opt-station-inventory-loaded'](); await tick();
  assert.match(get('status').textContent, /Absentes : 0 · Prêtes à envoyer : 0 · À vérifier : 1/);
  assert.doesNotMatch(get('status').textContent, /Toutes les bobines/);

  queuePreview([spool('B0000','present')]);
  now += 60001; emit(true); await tick();
  assert.equal(get('count').hidden, true);
  assert.match(get('status').textContent, /Toutes les bobines actives sont présentes/);
  const beforeHidden = calls.length;
  document.hidden = true; now += 60001; emit(true); await tick();
  assert.equal(calls.length, beforeHidden);
  document.hidden = false; document.body.dataset.tab = 'printer'; emit(true); await tick();
  assert.equal(calls.length, beforeHidden);

  // Opening the dialog while a count is loading shares the read, but still
  // requires an explicit click on Send before any export can happen.
  document.body.dataset.tab = 'inventory';
  const pendingItems = [spool('B0001')];
  answers.push(new Promise(r => { resolve = r; }));
  emit(true); await tick();
  const duringRead = calls.length;
  await click('open'); assert.equal(calls.length, duringRead);
  resolve({body:{organization:'Test team', items:pendingItems, counts:{total:1,missing:1,ready:1,present:0,blocked:0}}});
  await tick(); await tick();
  assert.equal(get('send').disabled, false);
  assert.equal(get('count').textContent, '1');
  await click('close');
  answers.push(new Promise(r => { resolve = r; }));
  events['opt-station-inventory-loaded'](); await tick();
  emit(false);
  resolve({body:{items:pendingItems, counts:{total:1,missing:1,ready:1,present:0,blocked:0}}});
  await tick(); await tick();
  assert.equal(get('count').hidden, true); // A late reply cannot restore stale access or counts.
  assert.match(get('status').textContent, /Accès complet requis/);
  queuePreview([]); emit(true); await tick();
  assert.match(get('status').textContent, /Aucune bobine active/);
  assert.ok(calls.slice(indicatorStart).every(call => call.url === '/api/inventory/connect/preview'));
  assert.equal(answers.length, 0);
  console.log('Bulk export: inventory counts, unknown/error states, shared reads, explicit serial writes, stop, retry, access loss and safe text verified.');
})().catch(error => { console.error(error); process.exitCode = 1; });
