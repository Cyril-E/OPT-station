// Controlled browser API doubles: no OS notification and no permission prompt.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '../openprinttag_app/static');
const catalog = JSON.parse(fs.readFileSync(path.join(root, 'translations.js'), 'utf8').split('Object.freeze(')[1].split(/\);\s*$/)[0]);
const source = fs.readFileSync(path.join(root, 'notifications.js'), 'utf8');
const key = 'opt-station-notifications-v1';
const settings = {enabled: true, finished: true, intervention: true};
const tick = () => new Promise(resolve => setImmediate(resolve));

function harness(options = {}) {
  const store = options.store || new Map(), notifications = [], streams = [], elements = new Map();
  let requested = 0, focused = 0, throwNotification = false, unavailable = options.unavailable || false;
  let now = Date.now();
  class ClockDate extends Date { static now() { return now; } }
  const events = () => ({handlers: new Map(), addEventListener(name, fn) { const list = this.handlers.get(name) || []; list.push(fn); this.handlers.set(name, list); }, async emit(name, value = {}) { for (const fn of this.handlers.get(name) || []) await fn(value); }});
  const document = {...events(), visibilityState: 'visible', documentElement: {lang: options.language || 'fr'}, getElementById(id) {
    if (!elements.has(id)) elements.set(id, {...events(), id, disabled: false, hidden: false, checked: false, textContent: '', clicks: 0, click() { this.clicks++; }});
    return elements.get(id);
  }};
  class Notification {
    static permission = options.permission || 'default';
    static async requestPermission() { requested++; Notification.permission = options.reply || 'granted'; return Notification.permission; }
    constructor(title, value) { if (throwNotification) throw Error('OS unavailable'); this.title = title; this.options = value; notifications.push(this); }
    close() { this.closed = true; if (this.onclose) this.onclose(); }
  }
  class EventSource {
    constructor(url) { assert.equal(url, '/api/printer/events'); Object.assign(this, events()); streams.push(this); }
    close() { this.closed = true; }
  }
  const window = {...events(), isSecureContext: options.secure !== false, Notification, EventSource,
    focus() { focused++; }, localStorage: {
      getItem(k) { if (unavailable) throw Error('storage blocked'); return store.get(k) ?? null; },
      setItem(k, value) { if (unavailable) throw Error('storage blocked'); store.set(k, value); }
    }, OPT_I18N: {init() {}, msg(value, ...args) { return (document.documentElement.lang === 'en' ? catalog[value] ?? value : value).replace(/\{(\d+)\}/g, (_, i) => String(args[i])); },
      text(element, value) { element.textContent = value; }, message(value) { return document.documentElement.lang === 'en' ? catalog[value] ?? value : value; }}};
  if (options.unsupported) delete window.Notification;
  const navigator = {locks: options.locks || {request: async (_, fn) => fn()}, permissions: {query: async () => events()}};
  const context = vm.createContext({window, document, navigator, console, Date: ClockDate});
  vm.runInContext(source, context);
  const emit = (stream, kind, value) => stream.emit(kind, {data: JSON.stringify(value)});
  return {window, document, Notification, store, notifications, streams, elements, emit,
    get requested() { return requested; }, get focused() { return focused; },
    control: id => document.getElementById('notifications-' + id),
    access: value => document.emit('opt-station-status', {detail: {access: value}}),
    async change(id, checked) { const el = this.control(id); el.checked = checked; await el.emit('change'); },
    fail(value) { throwNotification = value; },
    advance(value) { now += value; },
    storage(value) { unavailable = value; }};
}

const event = (id = 'server:1', kind = 'finished') => ({id, kind, printer_name: 'Prusa test', filename: 'Pièce française.gcode', state: kind === 'finished' ? 'FINISHED' : 'ATTENTION'});

(async () => {
  const page = harness();
  assert.equal(page.requested, 0); assert.equal(page.streams.length, 0);
  await page.access(true);
  assert.equal(page.requested, 0); assert.equal(page.control('authorize').disabled, false);
  await page.control('authorize').emit('click');
  assert.equal(page.requested, 1); assert.equal(page.streams.length, 1);
  assert.equal(JSON.parse(page.store.get(key)).enabled, true);
  const stream = page.streams[0];
  await page.emit(stream, 'status', {configured: true, connected: true});
  assert.equal(page.control('state').textContent, 'Suivi des alertes actif');
  // No dependence on the internal Printer tab or foreground visibility.
  page.document.visibilityState = 'hidden';
  await page.document.emit('visibilitychange');
  assert.equal(stream.closed, undefined);
  await page.emit(stream, 'printer', event()); await tick();
  assert.equal(page.notifications.length, 1);
  assert.equal(page.notifications[0].options.body, 'Prusa test · Pièce française.gcode');
  await page.emit(stream, 'printer', event()); await tick();
  assert.equal(page.notifications.length, 1);
  page.notifications[0].onclick();
  assert.equal(page.focused, 1); assert.equal(page.document.getElementById('tab-printer').clicks, 1);
  assert.equal(page.notifications[0].closed, true);
  await page.emit(stream, 'printer', event('server:2', 'intervention')); await tick();
  assert.equal(page.notifications.length, 2);
  assert.match(page.notifications[1].options.body, /Vérifiez l’écran/);
  await page.emit(stream, 'printer', {id: 'bad', kind: 'unknown'}); await stream.emit('printer', {data: 'invalid'});
  assert.equal(page.notifications.length, 2);
  await page.change('finished', false);
  assert.equal(stream.closed, true);
  const second = page.streams.at(-1);
  await page.emit(second, 'printer', event('server:3')); await tick();
  assert.equal(page.notifications.length, 2);
  await page.emit(second, 'printer', {...event('server:4', 'intervention'), message: 'Filament absent <photo>'}); await tick();
  assert.equal(page.notifications.at(-1).options.body, 'Prusa test · Filament absent <photo>');
  await page.change('enabled', false);
  assert.equal(second.closed, true);
  await page.emit(second, 'printer', event('server:5', 'intervention')); await tick();
  assert.equal(page.notifications.length, 3);
  await page.control('test').emit('click');
  assert.equal(page.notifications.at(-1).title, 'OPT Station · Test des notifications');
  assert.equal(page.streams.length, 2); // A test notification does not activate monitoring.

  const resumed = harness({store: page.store, permission: 'granted'});
  await resumed.access(true);
  assert.equal(resumed.streams.length, 0); assert.equal(resumed.control('finished').checked, false);
  await resumed.change('enabled', true);
  assert.equal(resumed.streams.length, 1);
  await resumed.access(false); assert.equal(resumed.streams[0].closed, true);
  await resumed.access(true); assert.equal(resumed.streams.length, 2);
  resumed.Notification.permission = 'denied';
  await resumed.document.emit('visibilitychange');
  assert.equal(resumed.streams[1].closed, true);
  assert.equal(resumed.control('state').textContent, 'Notifications bloquées');
  assert.equal(resumed.requested, 0);

  for (const options of [{secure: false}, {unsupported: true}, {permission: 'denied'}]) {
    const blocked = harness(options); await blocked.access(true);
    await blocked.control('authorize').emit('click'); await blocked.control('test').emit('click');
    assert.equal(blocked.requested, 0); assert.equal(blocked.streams.length, 0); assert.equal(blocked.notifications.length, 0);
  }
  const denied = harness({reply: 'denied'}); await denied.access(true); await denied.control('authorize').emit('click');
  assert.equal(denied.requested, 1); assert.equal(denied.streams.length, 0); assert.equal(denied.control('enabled').checked, false);

  // Two tabs share an origin-wide lock and delivery history; only one produces an OS alert.
  const shared = new Map([[key, JSON.stringify(settings)]]);
  let queue = Promise.resolve();
  const locks = {request(_, fn) { const task = queue.then(fn); queue = task.catch(() => {}); return task; }};
  const a = harness({store: shared, permission: 'granted', locks}), b = harness({store: shared, permission: 'granted', locks});
  await a.access(true); await b.access(true);
  await Promise.all([a.emit(a.streams[0], 'printer', event('same-event')), b.emit(b.streams[0], 'printer', event('same-event'))]);
  await queue; await tick();
  assert.equal(a.notifications.length + b.notifications.length, 1);
  const reload = harness({store: shared, permission: 'granted', locks}); await reload.access(true);
  await reload.emit(reload.streams[0], 'printer', event('same-event')); await queue;
  assert.equal(reload.notifications.length, 0);
  a.document.documentElement.lang = 'en';
  await a.emit(a.streams[0], 'printer', event('english-event')); await queue;
  assert.equal(a.notifications.at(-1).title, 'OPT Station · Print finished');
  assert.equal(a.notifications.at(-1).options.body, 'Prusa test · Pièce française.gcode');

  const broken = harness({unavailable: true, permission: 'granted'}); await broken.access(true);
  await broken.change('enabled', true);
  assert.equal(broken.control('storage-note').hidden, false);
  await broken.emit(broken.streams[0], 'printer', event()); await tick();
  assert.equal(broken.notifications.length, 1);
  broken.fail(true);
  await broken.emit(broken.streams[0], 'printer', event('failure')); await tick();
  assert.match(broken.control('result').textContent, /n’a pas pu/);
  broken.fail(false);
  await broken.emit(broken.streams[0], 'printer', event('failure')); await tick();
  assert.equal(broken.notifications.length, 2); // A constructor failure does not discard the event.
  await broken.document.emit('freeze'); assert.equal(broken.streams[0].closed, true);
  await broken.document.emit('resume'); assert.equal(broken.streams.length, 2);
  await broken.window.emit('pagehide'); assert.equal(broken.streams[1].closed, true);
  await broken.window.emit('pageshow'); assert.equal(broken.streams.length, 3);
  const buffered = broken.streams.at(-1);
  broken.advance(60000);
  await broken.emit(buffered, 'status', {connected: true, configured: true});
  assert.equal(buffered.closed, true); assert.equal(broken.streams.length, 4);
  await broken.emit(buffered, 'printer', event('old-buffered-event')); await tick();
  assert.equal(broken.notifications.length, 2); // A sleeping computer cannot replay a buffered finish.
  console.log('Notifications: explicit permission, background stream, selections, click, persistence, cross-tab deduplication, access loss, EN, errors and lifecycle verified.');
})().catch(error => { console.error(error); process.exitCode = 1; });
