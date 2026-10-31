// Browser-independent locale state tests. Run with: node tests/interface_i18n.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const staticRoot = path.join(__dirname, '../openprinttag_app/static');

function environment(saved = null, unavailable = false) {
  const elements = [];
  class Element {
    constructor(id, content = '') {
      this.id = id; this.dataset = {}; this.attributes = {}; this.value = ''; this.hidden = true;
      this.isConnected = true; this.childNodes = [{nodeType: 3, textContent: content, isConnected: true, parentNode: this}];
      elements.push(this);
    }
    addEventListener() {}
    hasAttribute(name) { return Object.hasOwn(this.attributes, name); }
    getAttribute(name) { return this.attributes[name]; }
    setAttribute(name, value) { this.attributes[name] = value; }
    get textContent() { return this.childNodes.map(node => node.textContent).join(''); }
    get firstChild() { return this.childNodes[0] || null; }
    append(node) { node.parentNode = this; this.childNodes.push(node); }
    set textContent(value) {
      this.childNodes.forEach(node => { node.isConnected = false; });
      this.childNodes = [{nodeType: 3, textContent: String(value), isConnected: true, parentNode: this}];
    }
  }
  const language = new Element('language-select'), note = new Element('language-storage-note');
  const staticLabel = new Element('static', ' Configuration '); staticLabel.dataset.i18n = '';
  const placeholder = new Element('placeholder'); placeholder.dataset.i18nAttrs = 'placeholder'; placeholder.setAttribute('placeholder', 'Non renseigné');
  const user = new Element('user'); user.value = 'Inconnu';
  const label = new Element('label');
  const nestedLabel = new Element('nested-label'), nestedInput = new Element('nested-input');
  nestedInput.value = 'rtsp://camera.example/live';
  const store = new Map(saved ? [['opt-station-language', saved]] : []);
  const document = {documentElement: {lang: 'fr'}, readyState: 'complete', addEventListener() {}, dispatchEvent() {},
    getElementById: id => elements.find(element => element.id === id),
    querySelectorAll: selector => elements.filter(element => {
      const key = {'[data-i18n]':'i18n','[data-i18n-attrs]':'i18nAttrs','[data-msg]':'msg','[data-msg-attrs]':'msgAttrs'}[selector];
      return Object.hasOwn(element.dataset, key);
    })};
  const window = {addEventListener() {}, localStorage: {
    getItem(key) { if (unavailable) throw Error('unavailable'); return store.get(key) ?? null; },
    setItem(key, value) { if (unavailable) throw Error('unavailable'); store.set(key, value); }}};
  const context = vm.createContext({window, document, CustomEvent: class {constructor(name, options) {this.type=name;this.detail=options.detail;}}});
  vm.runInContext(fs.readFileSync(path.join(staticRoot, 'translations.js'), 'utf8'), context);
  vm.runInContext(fs.readFileSync(path.join(staticRoot, 'i18n.js'), 'utf8'), context);
  return {i18n: window.OPT_I18N, document, user, label, nestedLabel, nestedInput, staticLabel, placeholder, language, note, store};
}

const env = environment();
env.i18n.text(env.user, 'Inconnu');
env.i18n.text(env.label, env.i18n.msg('Depuis {0} jour{1}', 3, 's'));
env.i18n.text(env.nestedLabel, env.i18n.msg('Nom de la vue'));
env.nestedLabel.append(env.nestedInput);
env.i18n.setLanguage('en');
assert.equal(env.document.documentElement.lang, 'en');
assert.equal(env.staticLabel.textContent, ' Settings ');
assert.equal(env.placeholder.getAttribute('placeholder'), 'Not specified');
assert.equal(env.user.value, 'Inconnu');
assert.equal(env.user.textContent, 'Inconnu');
assert.equal(env.label.textContent, 'Stored for 3 days');
assert.equal(env.nestedLabel.firstChild.textContent, 'View name');
assert.equal(env.nestedLabel.childNodes[1], env.nestedInput);
assert.equal(env.nestedInput.isConnected, true);
assert.equal(env.nestedInput.value, 'rtsp://camera.example/live');
assert.equal(env.store.get('opt-station-language'), 'en');
assert.equal(env.language.value, 'en');
assert.equal(env.i18n.locale(), 'en-GB');
assert.equal(String(env.i18n.message('La région main nécessite 300 octets pour seulement 238 disponibles.')), 'Region main requires 300 bytes but only 238 are available.');
const raw = {main:{brand_name:'Inconnu',material_name:'Configuration'},aux:{storage_location:'En stock'},message:'Arrêt et redémarrage autorisés par le système.',detection_message:'Détection disponible sur le Raspberry Pi.'};
const response = env.i18n.messages(raw);
assert.equal(response.main, raw.main);
assert.equal(response.aux, raw.aux);
assert.equal(String(response.message), 'Shutdown and restart are permitted by the system.');
assert.equal(String(response.detection_message), 'Detection is available on the Raspberry Pi.');
env.i18n.setLanguage('fr');
assert.equal(env.staticLabel.textContent, ' Configuration ');
assert.equal(env.label.textContent, 'Depuis 3 jours');
assert.equal(env.nestedLabel.firstChild.textContent, 'Nom de la vue');
assert.equal(env.nestedLabel.childNodes[1], env.nestedInput);
assert.equal(env.nestedInput.value, 'rtsp://camera.example/live');
assert.equal(String(response.message), 'Arrêt et redémarrage autorisés par le système.');
assert.equal(env.user.value, 'Inconnu');
assert.equal(environment('en').i18n.getLanguage(), 'en');
const privateMode = environment(null, true);
privateMode.i18n.setLanguage('en');
assert.equal(privateMode.i18n.getLanguage(), 'en');
assert.equal(privateMode.note.hidden, false);
console.log('Locale runtime: switching, persistence, input preservation, backend messages and unavailable storage verified.');
