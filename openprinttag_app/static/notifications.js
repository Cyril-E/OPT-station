"use strict";
(() => {
  const I18n = window.OPT_I18N; I18n.init();
  const msg = I18n.msg, $ = id => document.getElementById(id);
  const key = "opt-station-notifications-v1", historyKey = "opt-station-notifications-seen-v1";
  const defaults = () => ({enabled: false, finished: true, intervention: true});
  let settings = defaults(), access = false, source = null, connection = "idle", observation = null;
  let storageAvailable = true, asking = false, suspended = false, generation = 0, feedback = null;
  const seen = new Set(), shown = new Set();
  const text = (id, value) => I18n.text($(id), value);
  const supported = () => window.isSecureContext && "Notification" in window && "EventSource" in window;
  const permission = () => "Notification" in window ? window.Notification.permission : "unsupported";
  function load() {
    try {
      const value = JSON.parse(window.localStorage.getItem(key));
      settings = value && typeof value === "object" ? Object.fromEntries(Object.keys(defaults()).map(k => [k, typeof value[k] === "boolean" ? value[k] : defaults()[k]])) : defaults();
    } catch { storageAvailable = false; }
  }
  function save() {
    try { window.localStorage.setItem(key, JSON.stringify(settings)); }
    catch { storageAvailable = false; }
  }
  function wanted() {
    return !suspended && supported() && permission() === "granted" && access && settings.enabled && (settings.finished || settings.intervention);
  }
  function render() {
    $("notifications-enabled").checked = settings.enabled;
    $("notifications-finished").checked = settings.finished;
    $("notifications-intervention").checked = settings.intervention;
    $("notifications-enabled").disabled = !access || !supported() || permission() !== "granted" || asking;
    $("notifications-finished").disabled = $("notifications-intervention").disabled = !access;
    $("notifications-authorize").disabled = !access || !supported() || permission() !== "default" || asking;
    $("notifications-test").disabled = !access || !supported() || permission() !== "granted" || asking;
    $("notifications-storage-note").hidden = storageAvailable;
    let state, detail;
    if (!window.isSecureContext) {
      state = msg("HTTPS requis"); detail = msg("Ouvrez la station en HTTPS et approuvez son certificat pour recevoir les notifications.");
    } else if (!supported()) {
      state = msg("Navigateur non compatible"); detail = msg("Utilisez Chrome sur un ordinateur pour les notifications de cette station.");
    } else if (!access) {
      state = msg("Accès complet requis"); detail = msg("Activez l’accès complet dans Paramètres → Accès distant pour recevoir les alertes de l’imprimante.");
    } else if (permission() === "denied") {
      state = msg("Notifications bloquées"); detail = msg("Autorisez les notifications dans les paramètres du site de Chrome, puis revenez ici.");
    } else if (permission() !== "granted") {
      state = msg("Autorisation nécessaire"); detail = msg("Cliquez sur Autoriser les notifications et acceptez la demande de Chrome.");
    } else if (!settings.enabled) {
      state = msg("Notifications désactivées"); detail = msg("Activez les alertes pour ce navigateur. Aucun ancien événement ne sera envoyé.");
    } else if (!settings.finished && !settings.intervention) {
      state = msg("Aucun événement choisi"); detail = msg("Sélectionnez au moins un événement à recevoir.");
    } else if (connection === "open" && observation?.connected) {
      state = msg("Suivi des alertes actif"); detail = msg("Laissez un onglet OPT Station ouvert, même en arrière-plan. Un clic sur une alerte ouvre l’onglet Imprimante.");
    } else if (connection === "open" && observation?.configured === false) {
      state = msg("Imprimante à configurer"); detail = msg("Activez le suivi PrusaLink dans Paramètres → Imprimante et caméras.");
    } else if (connection === "open") {
      state = msg("Imprimante injoignable"); detail = msg("Les alertes reprendront avec les prochains événements après le retour de la connexion à l’imprimante.");
    } else {
      state = msg("Connexion au suivi…"); detail = msg("Le suivi se reconnecte automatiquement. Les anciens événements ne sont pas rejoués.");
    }
    text("notifications-state", state); text("notifications-detail", detail);
    text("notifications-result", feedback ? I18n.message(feedback) : "");
  }
  function stop() {
    generation++;
    if (source) source.close();
    source = null; connection = "idle"; observation = null;
  }
  function sync() {
    if (!wanted()) stop();
    else if (!source) {
      const stream = new window.EventSource("/api/printer/events"); source = stream; connection = "connecting";
      const current = generation;
      let lastMessage = Date.now();
      stream.addEventListener("status", event => {
        if (source !== stream) return;
        // Après une longue suspension, jeter le flux tamponné et repartir de l'état courant.
        if (Date.now() - lastMessage > 45000) { stop(); sync(); return; }
        lastMessage = Date.now();
        try { observation = JSON.parse(event.data); connection = "open"; } catch { return; }
        if (!wanted()) stop();
        render();
      });
      stream.addEventListener("printer", event => {
        if (source !== stream || current !== generation || !wanted()) return;
        let value;
        try { value = JSON.parse(event.data); } catch { return; }
        if (!value || !["finished", "intervention"].includes(value.kind) || typeof value.id !== "string" || value.id.length > 100) return;
        if (settings[value.kind]) void deliver(value, current);
      });
      stream.addEventListener("access", () => { if (source === stream) { access = false; stop(); render(); } });
      stream.addEventListener("paused", () => { if (source === stream) { connection = "connecting"; observation = null; render(); } });
      stream.addEventListener("error", () => {
        if (source !== stream) return;
        connection = "connecting"; observation = null;
        if (!wanted()) stop();
        render();
      });
    }
    render();
  }
  function show(value) {
    const finished = value.kind === "finished", test = value.kind === "test";
    const title = test ? msg("OPT Station · Test des notifications") : finished ? msg("OPT Station · Impression terminée") : msg("OPT Station · Intervention requise");
    const name = typeof value.printer_name === "string" ? value.printer_name : msg("Imprimante");
    const filename = typeof value.filename === "string" && value.filename ? value.filename : msg("Travail en cours");
    const detail = value.state === "PAUSED" ? msg("Impression en pause. Vérifiez l’imprimante.") : msg("Vérifiez l’écran de l’imprimante pour poursuivre.");
    const body = test ? msg("Les notifications sont autorisées. Un clic ouvre le suivi de l’imprimante.")
      : finished ? msg("{0} · {1}", name, filename)
        : msg("{0} · {1}", name, typeof value.message === "string" && value.message ? value.message : detail);
    const notification = new window.Notification(title, {body, tag: "opt-station:" + value.id, icon: "/static/favicon.svg", renotify: false, lang: document.documentElement.lang});
    shown.add(notification);
    notification.onclick = () => { window.focus(); $(access ? "tab-printer" : "tab-configuration").click(); notification.close(); };
    notification.onclose = () => shown.delete(notification);
    notification.onerror = () => { feedback = msg("La notification n’a pas pu être affichée. Vérifiez les autorisations de Chrome et du système."); render(); };
    return notification;
  }
  async function deliver(value, current) {
    const send = () => {
      if (!wanted() || current !== generation || !settings[value.kind] || seen.has(value.id)) return;
      let history = [];
      try {
        const stored = JSON.parse(window.localStorage.getItem(historyKey));
        if (Array.isArray(stored)) history = stored.filter(id => typeof id === "string").slice(-128);
      } catch { storageAvailable = false; }
      if (history.includes(value.id)) return;
      try { show(value); }
      catch { feedback = msg("La notification n’a pas pu être affichée. Vérifiez les autorisations de Chrome et du système."); render(); return; }
      seen.add(value.id);
      if (seen.size > 128) seen.delete(seen.values().next().value);
      try { window.localStorage.setItem(historyKey, JSON.stringify([...history, value.id].slice(-128))); }
      catch { storageAvailable = false; }
    };
    try {
      if (navigator.locks?.request) await navigator.locks.request("opt-station-notification-delivery", send);
      else send();
    } catch { feedback = msg("La notification n’a pas pu être affichée. Vérifiez les autorisations de Chrome et du système."); render(); }
  }
  $("notifications-authorize").addEventListener("click", async () => {
    if (!access || !supported() || permission() !== "default" || asking) return;
    asking = true; feedback = null; render();
    try {
      const result = await window.Notification.requestPermission();
      if (result === "granted") { settings.enabled = true; save(); }
    } catch { feedback = msg("La notification n’a pas pu être affichée. Vérifiez les autorisations de Chrome et du système."); }
    finally { asking = false; sync(); }
  });
  ["enabled", "finished", "intervention"].forEach(name => {
    $("notifications-" + name).addEventListener("change", () => {
      if (!access) return;
      stop();
      settings[name] = $("notifications-" + name).checked;
      feedback = null; save(); sync();
    });
  });
  $("notifications-test").addEventListener("click", () => {
    if (!access || !supported() || permission() !== "granted") return;
    try { show({id: "test-" + Date.now(), kind: "test"}); feedback = msg("Notification de test envoyée. Si elle n’apparaît pas, vérifiez les notifications de Chrome dans les réglages du système et le mode Concentration."); }
    catch { feedback = msg("La notification n’a pas pu être affichée. Vérifiez les autorisations de Chrome et du système."); }
    render();
  });
  document.addEventListener("opt-station-status", event => { access = Boolean(event.detail.access); sync(); });
  document.addEventListener("opt-station-language", render);
  document.addEventListener("visibilitychange", sync);
  window.addEventListener("storage", event => { if (event.key === key || event.key === null) { load(); sync(); } });
  window.addEventListener("pagehide", () => { suspended = true; stop(); shown.forEach(n => n.close()); shown.clear(); });
  window.addEventListener("pageshow", () => { suspended = false; sync(); });
  document.addEventListener("freeze", () => { suspended = true; stop(); });
  document.addEventListener("resume", () => { suspended = false; sync(); });
  if (navigator.permissions?.query) {
    navigator.permissions.query({name: "notifications"}).then(status => status.addEventListener("change", sync)).catch(() => {});
  }
  load(); render();
})();
