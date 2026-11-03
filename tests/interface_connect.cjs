// A blocked Connect export can be corrected in place without inventing data or sending automatically.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '../openprinttag_app/static');
const markup = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const events = {}, elements = new Map(), answers = [], calls = [], dispatched = [];
class Element {
  constructor(id) { this.id = id; this.events = {}; this.children = []; this.value = ''; this.disabled = false; }
  addEventListener(name, callback) { this.events[name] = callback; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  showModal() { this.open = true; }
  close() { this.open = false; this.events.close?.(); }
  reset() { this.resets = (this.resets || 0) + 1; }
  reportValidity() { return this.valid !== false; }
  set innerHTML(_) { throw Error('Spool data must be rendered as text'); }
}
for (const [, id] of markup.matchAll(/\bid="([^"]+)"/g)) elements.set(id, new Element(id));
const get = name => elements.get('connect-export-' + name);
const document = {
  visibilityState: 'visible',
  getElementById(id) { assert.ok(elements.has(id), `Missing element: ${id}`); return elements.get(id); },
  createElement: () => new Element(),
  addEventListener(name, callback) { events[name] = callback; },
  dispatchEvent(event) { dispatched.push(event.type); }
};
const window = {addEventListener() {}, OPT_I18N: {
  locale: () => 'fr-FR', msg: value => value, message: value => value, messages: value => value,
  text: (element, value) => { element.textContent = value; }
}};
vm.runInNewContext(fs.readFileSync(path.join(root, 'connect.js'), 'utf8'), {
  window, document, AbortController, Intl, Date, Boolean, Number,
  setTimeout, clearTimeout, setInterval() {}, clearInterval() {},
  CustomEvent: class { constructor(type) { this.type = type; } },
  fetch(url, options) {
    calls.push({url, options});
    assert.ok(answers.length, `Unexpected request: ${url}`);
    const {status = 200, body} = answers.shift();
    return Promise.resolve({ok: status === 200, json: async () => body});
  }
});
const blocked = {id:'fixture', version:7, notes_revision:2,
  main:{nominal_netto_full_weight:1000}, aux:{consumed_weight:850}};
const materials = [{value:'PLA',label:'PLA'}, {value:'PETG',label:'PETG'}];
const edit = () => get('values-form').events.input();
const save = () => get('values-form').events.submit({preventDefault() {}, currentTarget:get('values-form')});
const emit = access => events['opt-station-status']({detail:{access}});

(async () => {
  await window.OPT_CONNECT_EXPORT.open(blocked, materials);
  assert.equal(calls.length, 0); // No full access: no preview or correction.
  emit(true);
  answers.push({status:422, body:{detail:'Renseignez la marque et la matière avant l’envoi vers Connect.'}});
  await window.OPT_CONNECT_EXPORT.open(blocked, materials);
  assert.equal(get('dialog').open, true);
  assert.equal(get('correction').open, true);
  assert.equal(get('send').disabled, true);
  assert.equal(get('brand').value, '');
  assert.equal(get('material').value, '');
  assert.deepEqual(get('material').children.map(x => x.value), ['', 'PLA', 'PETG']);
  assert.equal(get('consumed').value, 850);
  assert.equal(get('actual').value, ''); // An unknown measured weight stays unknown.
  assert.equal(get('nominal').value, 1000);
  assert.match(markup, /id="connect-export-brand"[^>]*required/);
  assert.match(markup, /id="connect-export-material"[^>]*required/);
  get('values-form').valid = false;
  await save();
  assert.equal(calls.length, 1); // Native required-field validation stops saving.
  get('values-form').valid = true;
  get('brand').value = ' Fixture brand '; get('material').value = 'PETG'; edit();
  events['opt-station-language']();
  assert.equal(get('brand').value, ' Fixture brand '); // Preserve typed data on language changes.
  assert.equal(get('send').disabled, true);
  const corrected = {...blocked, version:8, main:{...blocked.main,brand_name:'Fixture brand',material_type:'PETG'}};
  answers.push({body:{item:corrected, updated:true, rfid_written:false}},
    {body:{version:8, notes_revision:2, disposition:'create', fingerprint:'f'.repeat(64),
      initial_weight:1000, consumed_weight:850, remaining_weight:150, name:'Fixture', organization:'Test'}});
  const pending = save();
  assert.equal(get('values-fields').disabled, true);
  await save(); // A double click cannot save twice.
  await pending;
  assert.equal(calls.length, 3);
  assert.deepEqual(JSON.parse(calls[1].options.body), {version:7,brand_name:'Fixture brand',material_type:'PETG',
    nominal_initial_weight:1000, actual_initial_weight:null, consumed_weight:850});
  assert.deepEqual(JSON.parse(calls[2].options.body), {version:8,notes_revision:2});
  assert.equal(calls.some(x => x.url.endsWith('/export')), false); // Saving never sends the spool.
  assert.equal(dispatched.includes('opt-station-inventory-updated'), true);
  assert.equal(get('send').disabled, false);
  edit();
  await get('send').events.click();
  assert.equal(calls.length, 3); // A changed form invalidates the old preview.
  answers.push({status:409, body:{detail:'Cette fiche a changé.'}});
  await save();
  assert.equal(get('brand').value, ' Fixture brand ');
  assert.equal(get('send').disabled, true);
  assert.equal(get('result').textContent, 'Cette fiche a changé.');
  emit(false);
  assert.equal(get('dialog').open, false);
  assert.equal(get('values-fields').disabled, true);
  assert.equal(get('send').disabled, true);
  assert.equal(answers.length, 0);
  console.log('Connect export: missing brand/material, in-place correction, unknown mass, preserved consumption, fresh preview, no automatic send, conflicts and access loss verified.');
})().catch(error => { console.error(error); process.exitCode = 1; });
