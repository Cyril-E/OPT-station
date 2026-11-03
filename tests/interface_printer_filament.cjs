// Drive the printer poll so stale readings and job changes exercise the production render path.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
class Element {
  constructor() {
    this.value = ""; this.textContent = ""; this.children = [];
    this.classList = {toggle() {}, add() {}, remove() {}};
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  addEventListener() {}
  removeAttribute() {}
  get lines() { return [this.textContent, ...this.children.flatMap(node => node.lines)].filter(Boolean); }
}
const events = {}, elements = new Map();
const document = {
  visibilityState: "visible",
  createElement: () => new Element(),
  getElementById(id) {
    if (!elements.has(id)) elements.set(id, new Element());
    return elements.get(id);
  },
  addEventListener(name, callback) { events[name] = callback; },
  dispatchEvent() {}
};
const window = {addEventListener() {}, OPT_I18N: {
  init() {}, locale: () => "fr-FR", messages: value => value,
  msg: (value, ...args) => value.replace(/\{(\d+)\}/g, (_, i) => args[i]),
  text: (element, value) => { element.textContent = String(value); }
}};
const now = new Date().toISOString(), expired = new Date(Date.now() - 180000).toISOString();
const spool = {instance_uuid: "spool", printer_uuid: "printer", tool_id: "1"};
const estimate = {...spool, job_id: 7, filename: "part.bgcode", checked_at: now,
  model_weight_g: 117.87, remaining_estimate_g: 104.9043, spool_remaining_g: 136, margin_estimate_g: 31.0957};
const connection = {connected: true, checked_at: now, job_filament: estimate};
const snapshot = {connected: true, observed_at: now, printer: {state: "PRINTING"}, connect: connection,
  job: {id: 7, consistent: true, filename: "part.bgcode"}};
let response = snapshot, requests = 0;
vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../openprinttag_app/static/printer.js"), "utf8"), {
  document, window, AbortController, Date, Intl, setTimeout, clearTimeout, setInterval() {}, clearInterval() {},
  CustomEvent: class {}, fetch: async () => {
    requests++;
    if (!response) throw new TypeError("Disconnected");
    return {ok: true, json: async () => response};
  }
});
const view = (cloud = connection) => window.OPT_PRINTER.filamentForecast(spool, cloud);
const forecast = edits => view({...connection, job_filament: {...estimate, ...edits}}).lines;
const tick = () => new Promise(resolve => setImmediate(resolve));
const poll = async value => {
  response = value;
  events["opt-printer-refresh"]();
  await tick();
};
(async () => {
  assert.equal(view(), null);
  events["opt-station-status"]({detail: {access: true}});
  events["opt-station-tab"]({detail: {tab: "printer"}});
  await tick();
  assert.equal(requests, 1);
  assert.ok(view().lines.includes("Bobine suffisante"));
  for (const value of ["117,87 g", "104,9 g", "136 g", "31,1 g"]) assert.ok(view().lines.includes(value));
  const shortage = forecast({margin_estimate_g: -14.5, spool_remaining_g: 90.4043});
  for (const value of ["Bobine insuffisante", "0 g", "Il manquerait 14,5 g pour terminer."]) assert.ok(shortage.includes(value));
  assert.ok(forecast({margin_estimate_g: -0.001}).includes("Il manquerait < 0,01 g pour terminer."));
  assert.ok(forecast({margin_estimate_g: 0}).includes("Bobine suffisante"));
  const partial = forecast({remaining_estimate_g: null, margin_estimate_g: null});
  assert.ok(partial.includes("117,87 g") && partial.includes("Estimation indisponible"));
  assert.ok(partial.includes("Inconnu") && !partial.includes("0 g"));
  for (const edits of [{instance_uuid: "other"}, {printer_uuid: "other"}, {tool_id: "2"},
    {job_id: 8}, {filename: "other.bgcode"}, {filename: ""}, {checked_at: expired}]) {
    assert.deepEqual(forecast(edits), ["Filament pour cette impression", "Estimation indisponible"]);
  }
  assert.ok(view({...connection, stale: true}).lines.includes("Estimation indisponible"));
  assert.ok(view({...connection, poll_seconds: 900, job_filament: {...estimate,
    checked_at: new Date(Date.now() - 121000).toISOString()}}).lines.includes("Estimation indisponible"));
  await poll(null); // The old Connect response may still be cached after a PrusaLink failure.
  assert.ok(view().lines.includes("Estimation indisponible"));
  for (const edit of [{observed_at: expired}, {job: {...snapshot.job, consistent: false}},
    {job: {...snapshot.job, filename: null}}, {job: {...snapshot.job, id: 8}}]) {
    await poll({...snapshot, ...edit});
    assert.ok(view().lines.includes("Estimation indisponible"));
  }
  await poll({...snapshot, printer: {state: "FINISHED"}});
  assert.equal(view(), null);
  await poll(snapshot);
  events["opt-station-status"]({detail: {access: false}});
  assert.equal(view(), null);
  console.log("Printer filament forecast: quantities, shortage, unknowns, identities, stale data, completed job and access loss verified.");
})().catch(error => { console.error(error); process.exitCode = 1; });
