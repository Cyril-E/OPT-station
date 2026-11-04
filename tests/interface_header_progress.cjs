// Exercise the existing PrusaLink poll across tabs. No printer or network is contacted.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../openprinttag_app/static/printer.js"), "utf8");
const tick = () => new Promise(resolve => setImmediate(resolve));
function harness() {
  let now = Date.now(), reply, pending = null, language = "fr";
  class Clock extends Date { static now() { return now; } }
  const events = () => ({handlers: {}, addEventListener(name, fn) { this.handlers[name] = fn; },
    emit(name, detail) { this.handlers[name]?.({detail}); }});
  class Element {
    constructor() {
      Object.assign(this, events());
      this.textContent = ""; this.value = ""; this.hidden = false; this.children = []; this.attrs = {};
      const classes = new Set();
      this.classList = {toggle(name, enabled) { enabled ? classes.add(name) : classes.delete(name); },
        add: name => classes.add(name), remove: name => classes.delete(name), contains: name => classes.has(name)};
    }
    append(...nodes) { this.children.push(...nodes); }
    replaceChildren(...nodes) { this.children = nodes; }
    removeAttribute(name) { delete this.attrs[name]; if (name === "value") this.value = ""; }
    setAttribute(name, value) { this.attrs[name] = String(value); }
  }
  const elements = new Map(), requests = [], timers = [];
  const document = {...events(), visibilityState: "visible", createElement: () => new Element(),
    getElementById(id) { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); }, dispatchEvent() {}};
  const window = {...events(), OPT_I18N: {init() {}, locale: () => language === "fr" ? "fr-FR" : "en-US",
    msg(value, ...args) { return {toString: () => (language === "en" && value === "Impression en cours" ? "Printing" : value).replace(/\{(\d+)\}/g, (_, i) => args[i])}; },
    messages: value => value, message: value => value, text(el, value) { el.textContent = String(value ?? ""); },
    attribute(el, key, value) { el.setAttribute(key, value); }}};
  vm.runInNewContext(source, {window, document, Date: Clock, Intl, AbortController, URL, CustomEvent: class {},
    setTimeout, clearTimeout, setInterval(fn) { timers.push(fn); return timers.length; }, clearInterval() {},
    fetch: async url => {
      requests.push(url);
      if (pending) await pending;
      if (reply === null) throw new TypeError("Disconnected");
      return {ok: true, json: async () => url === "/api/configuration/printer" ? {
        revision: 1, printer: {enabled: true, name: "Test", url: "", auth: "none", username: ""},
        cameras: [], connect: {}, camera_capture_available: false
      } : reply};
    }});
  const el = id => document.getElementById(id);
  const snapshot = (state = "PRINTING", progress = 42.5) => ({configured: true, connected: true, observed_at: new Date(now).toISOString(),
    printer: {state}, cameras: [], job: {id: 7, consistent: true, progress, state: "PRINTING", filename: "piece.bgcode"}});
  reply = snapshot();
  return {document, window, requests, timers, el, snapshot,
    async access(value) { document.emit("opt-station-status", {access: value}); await tick(); },
    async tab(tab) { document.emit("opt-station-tab", {tab}); await tick(); },
    async poll(value) { reply = value; timers[0](); await tick(); },
    async visible(value) { document.visibilityState = value; document.emit("visibilitychange"); await tick(); },
    async language(value) { language = value; document.emit("opt-station-language"); await tick(); },
    advance(ms) { now += ms; },
    defer() { let resolve; pending = new Promise(r => { resolve = r; }); return async () => { pending = null; resolve(); await tick(); }; }};
}
(async () => {
  const page = harness(), panel = page.el("header-printer-progress"), state = page.el("header-printer-state"), percent = page.el("header-printer-percent"), meter = page.el("header-printer-meter"), note = page.el("header-printer-note");
  assert.equal(panel.hidden, true);
  assert.equal(page.requests.length, 0);
  assert.equal(page.timers.length, 1); // The original timer is shared by the header and Printer tab.
  await page.tab("inventory");
  await page.access(true);
  assert.equal(page.requests.length, 1);
  assert.equal(panel.hidden, false);
  assert.equal(state.textContent, "Impression en cours");
  assert.equal(percent.textContent, "42,5 %");
  assert.equal(meter.value, 42.5);
  assert.equal(note.hidden, true);
  for (const tab of ["read", "write", "configuration", "inventory"]) {
    await page.tab(tab);
    await page.poll(page.snapshot("PRINTING", 50));
    assert.equal(panel.hidden, false);
    assert.equal(meter.value, 50);
  }
  assert.ok(page.requests.every(url => ["/api/printer/status", "/api/configuration/printer"].includes(url)));
  await page.poll({...page.snapshot(), cameras: [{id: "test-camera", name: "Camera"}],
    job: {...page.snapshot().job, thumbnail_available: true}});
  await page.language("en"); await page.language("fr");
  assert.equal(page.el("printer-thumbnail").src, undefined);
  assert.equal(page.el("printer-camera-grid").children.length, 0);
  assert.ok(!page.requests.some(url => url.includes("/image")));
  for (const [name, title] of [["PAUSED", "En pause"], ["ATTENTION", "Intervention requise"]]) {
    await page.poll(page.snapshot(name, 61));
    assert.equal(state.textContent, title);
    assert.equal(panel.classList.contains("waiting"), true);
    assert.equal(meter.value, 61);
  }
  for (const progress of [null, undefined, "70", NaN, Infinity, -1, 101]) {
    await page.poll({...page.snapshot(), job: {...page.snapshot().job, progress}});
    assert.equal(percent.textContent, "—");
    assert.equal(meter.hidden, true);
    assert.equal(note.textContent, "Avancement indisponible");
  }
  for (const progress of [0, 100]) {
    await page.poll(page.snapshot("PRINTING", progress));
    assert.equal(meter.hidden, false); assert.equal(meter.value, progress);
  }
  await page.poll({...page.snapshot(), job: {...page.snapshot().job, consistent: false}});
  assert.equal(meter.hidden, true);
  await page.poll(page.snapshot());
  await page.language("en");
  assert.equal(state.textContent, "Printing"); assert.equal(percent.textContent, "42.5 %");
  await page.language("fr");
  await page.poll(null);
  assert.equal(panel.hidden, false); assert.equal(meter.value, 42.5);
  assert.equal(state.textContent, "Dernier avancement connu");
  assert.equal(note.textContent, "Connexion à vérifier");
  assert.equal(panel.classList.contains("stale"), true);
  await page.poll(page.snapshot());
  assert.equal(panel.classList.contains("stale"), false);
  for (const observed_at of ["invalid", null, new Date(Date.now() + 120000).toISOString()]) {
    await page.poll({...page.snapshot(), observed_at});
    assert.equal(panel.classList.contains("stale"), true);
  }
  await page.poll(page.snapshot());
  page.document.emit("opt-station-offline");
  assert.equal(panel.classList.contains("stale"), true);
  await page.poll(page.snapshot());
  await page.visible("hidden");
  const count = page.requests.length;
  page.advance(31000);
  await page.poll(page.snapshot()); // Hidden tabs cannot fetch a newer observation.
  assert.equal(page.requests.length, count);
  assert.equal(panel.classList.contains("stale"), true);
  await page.visible("visible");
  assert.equal(page.requests.length, count + 1);
  assert.equal(panel.classList.contains("stale"), false);
  for (const printerState of ["IDLE", "READY", "BUSY", "FINISHED", "STOPPED", "ERROR"]) {
    await page.poll(page.snapshot(printerState)); assert.equal(panel.hidden, true);
  }
  await page.poll({...page.snapshot("ATTENTION"), job: {}});
  assert.equal(panel.hidden, true); // An unrelated printer warning is not an active print.
  for (const jobState of ["FINISHED", "STOPPED", "ERROR", "CANCELLED"]) {
    await page.poll({...page.snapshot(), job: {...page.snapshot().job, state: jobState}});
    assert.equal(panel.hidden, true);
  }
  await page.poll({...page.snapshot(), configured: false}); assert.equal(panel.hidden, true);
  await page.poll(page.snapshot());
  await page.access(false); assert.equal(panel.hidden, true);
  const before = page.requests.length;
  await page.poll(page.snapshot()); assert.equal(page.requests.length, before);
  await page.access(true); assert.equal(panel.hidden, false);
  // Switching views while the shared status request is pending must not discard it or duplicate it.
  const complete = page.defer();
  const loading = page.poll(page.snapshot("PRINTING", 73));
  await page.tab("printer"); await page.tab("inventory");
  await complete(); await loading;
  assert.equal(meter.value, 73);
  assert.equal(page.el("printer-thumbnail").attrs.src, undefined);
  assert.ok(!page.requests.some(url => url.includes("/image") || url.includes("/thumbnail")));
  const finish = page.defer();
  const pending = page.poll(page.snapshot("PRINTING", 91));
  await page.access(false);
  await finish(); await pending;
  assert.equal(panel.hidden, true); // A late answer cannot expose status after access has ended.
  console.log("Header progress: shared polling, all tabs, pause/intervention, missing progress, freshness, reconnect, completion, access and view transitions verified.");
})().catch(error => { console.error(error); process.exitCode = 1; });
