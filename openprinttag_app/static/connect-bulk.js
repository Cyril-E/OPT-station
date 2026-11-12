"use strict";

// A preview only reads Connect. Each confirmed write is checked again on the Pi.
(() => {
  const I18n = window.OPT_I18N, msg = I18n.msg;
  const $ = (suffix) => document.getElementById("connect-bulk-" + suffix);
  let access = false, busy = false, sending = false, stop = false, epoch = 0;
  let preview = null, rows = [], report = false;
  let summary = null, summaryPhase = "unchecked", summaryEpoch = 0, summaryAttempt = 0, summaryRequest = null;
  const text = (suffix, value) => I18n.text($(suffix), value);
  function node(tag, className, value) {
    const element = document.createElement(tag); element.className = className;
    if (value !== undefined) I18n.text(element, value);
    return element;
  }
  async function request(path, body) {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 60000);
    try {
      const response = await fetch(path, {method: "POST", credentials: "same-origin", cache: "no-store",
        signal: controller.signal, headers: {"Content-Type": "application/json"}, body: JSON.stringify(body || {})});
      const value = await response.json();
      if (!response.ok) {
        const error = new Error(String(I18n.message(typeof value.detail === "string" ? value.detail : msg("Lecture Connect indisponible."))));
        error.status = response.status; throw error;
      }
      return value;
    } catch (error) {
      if (error.name === "AbortError" || error instanceof TypeError || error instanceof SyntaxError) {
        throw new Error(String(msg("Connexion interrompue. Vérifiez à nouveau l’entrepôt avant de reprendre ; aucun envoi n’est relancé automatiquement.")));
      }
      throw error;
    } finally { clearTimeout(timer); }
  }
  // This shared request only reads the warehouse. Background counts never send
  // a spool and never turn into a confirmation preview on their own.
  function readPreview() {
    if (!summaryRequest) {
      const pending = request("/api/inventory/connect/preview").finally(() => {
        if (summaryRequest === pending) summaryRequest = null;
      });
      summaryRequest = pending;
    }
    return summaryRequest;
  }
  function renderSummary() {
    const counts = summary?.counts;
    $("count").hidden = !counts?.missing;
    text("count", counts ? String(counts.missing) : "");
    $("open").dataset.pending = String(Boolean(counts?.missing));
    let message;
    if (!access) message = msg("Accès complet requis pour vérifier Prusa Connect.");
    else if (sending) message = msg("Envoi et relecture…");
    else if (summaryPhase === "checking") message = msg("Vérification de l’entrepôt Prusa Connect…");
    else if (summaryPhase === "error") message = msg("Prusa Connect indisponible · présence des bobines à vérifier.");
    else if (!counts) message = msg("Présence dans Prusa Connect à vérifier.");
    else if (!counts.total) message = msg("Aucune bobine active à envoyer.");
    else if (!counts.missing && !counts.blocked) message = msg("Toutes les bobines actives sont présentes dans Prusa Connect.");
    else message = msg("Absentes : {0} · Prêtes à envoyer : {1} · À vérifier : {2}", counts.missing, counts.ready, counts.blocked);
    text("status", message);
  }
  function rememberSummary(value) {
    summary = value; summaryPhase = "ready"; summaryAttempt = Date.now();
    renderSummary();
  }
  function invalidateSummary() {
    summaryEpoch++; summary = null; summaryPhase = "unchecked"; summaryAttempt = 0;
    renderSummary();
  }
  async function refreshSummary() {
    if (!access || busy || summaryRequest || $("dialog").open || document.hidden
        || document.body.dataset.tab !== "inventory" || (summaryAttempt && Date.now() - summaryAttempt < 60000)) return;
    const current = ++summaryEpoch;
    summaryAttempt = Date.now(); summary = null; summaryPhase = "checking"; renderSummary();
    try {
      const value = await readPreview();
      if (access && current === summaryEpoch) rememberSummary(value);
    } catch {
      if (access && current === summaryEpoch) { summary = null; summaryPhase = "error"; renderSummary(); }
    }
  }
  function controls() {
    $("open").disabled = !access || busy;
    $("check").disabled = !access || busy;
    $("send").disabled = !access || busy || !preview || report || !rows.some(row => row.disposition === "create");
    $("send").hidden = report;
    $("close").disabled = busy;
    $("cancel").hidden = !sending;
    $("cancel").disabled = stop;
    text("send", msg("Envoyer les bobines manquantes ({0})", rows.filter(row => row.disposition === "create").length));
    renderSummary();
  }
  const label = row => ({
    create: msg("Prête à envoyer"), present: msg("Déjà présente · conservée"), blocked: msg("À corriger ou vérifier"),
    sending: msg("Envoi et relecture…"), sent: msg("Envoyée et vérifiée"),
    failed: msg("À vérifier avant de reprendre"), waiting: msg("Non envoyée")
  })[row.result || row.disposition];
  function render() {
    const present = rows.filter(row => (row.result || row.disposition) === "present").length;
    const sent = rows.filter(row => row.result === "sent").length;
    if (preview) {
      text("organization", msg("Organisation Connect : {0}", preview.organization));
      text("summary", report
        ? msg("{0} envoyées · {1} déjà présentes · {2} à traiter.", sent, present, rows.length - present - sent)
        : msg("{0} bobines actives · {1} absentes · {2} déjà présentes · {3} à vérifier.", preview.counts.total,
          preview.counts.missing, preview.counts.present, preview.counts.blocked));
    } else { text("organization", ""); text("summary", ""); }
    const list = $("items"); list.replaceChildren();
    for (const row of rows) {
      const item = node("li", "connect-bulk-item");
      const content = node("div", "connect-bulk-description");
      const title = row.name?.startsWith(row.spool_number + " · ") ? row.name
        : [row.spool_number, row.name === row.spool_number ? "" : row.name].filter(Boolean).join(" · ");
      content.append(node("strong", "", title));
      content.append(node("p", "fine-print", label(row)));
      if (row.message) content.append(node("p", "fine-print", I18n.message(row.message)));
      item.append(content);
      if (["blocked", "failed"].includes(row.result || row.disposition) && !busy) {
        const button = node("button", "button secondary small", msg("Vérifier la fiche")); button.type = "button";
        button.disabled = !access;
        button.addEventListener("click", () => {
          if (!access || busy) return;
          $("dialog").close(); preview = null; rows = []; report = false;
          document.dispatchEvent(new CustomEvent("opt-station-connect-correct", {detail: {id: row.id}}));
        });
        item.append(button);
      }
      list.append(item);
    }
    controls();
  }
  async function check() {
    if (!access || busy) return;
    const current = ++epoch; busy = true; report = false; preview = null; rows = [];
    const summaryCurrent = ++summaryEpoch;
    summary = null; summaryPhase = "checking";
    text("result", msg("Vérification des bobines actives dans l’entrepôt…")); render();
    try {
      const value = await readPreview();
      if (!access || current !== epoch) return;
      preview = value; rows = value.items;
      if (summaryCurrent === summaryEpoch) rememberSummary(value);
      text("result", rows.some(row => row.disposition === "create")
        ? msg("Seules les bobines absentes et prêtes seront envoyées après confirmation.")
        : msg("Aucune bobine prête à envoyer. Consultez le résultat de la vérification."));
    } catch (error) {
      if (access && current === epoch) {
        text("result", I18n.message(error.message));
        if (summaryCurrent === summaryEpoch) { summary = null; summaryPhase = "error"; summaryAttempt = Date.now(); }
      }
    }
    finally { busy = false; render(); }
  }
  async function send() {
    if (!access || busy || !preview || report) return;
    const pending = rows.filter(row => row.disposition === "create");
    if (!pending.length) return;
    const current = epoch; busy = true; sending = true; stop = false; report = true;
    invalidateSummary();
    for (const row of pending) row.result = "waiting";
    render();
    try {
      for (const [index, row] of pending.entries()) {
        if (stop || !access || current !== epoch) break;
        row.result = "sending";
        text("result", msg("Envoi {0} sur {1} · {2}", index + 1, pending.length, row.spool_number)); render();
        try {
          const result = await request(`/api/inventory/${encodeURIComponent(row.id)}/connect/export-missing`,
            {version: row.version, notes_revision: row.notes_revision, fingerprint: row.fingerprint});
          if (!access || current !== epoch) return;
          if (result.status === "already_present" && !result.created) row.result = "present";
          else if (result.created && result.verified && result.visible_in_connect) row.result = "sent";
          else {
            row.result = "failed"; row.message = String(msg("Le résultat de cet envoi reste à vérifier dans l’entrepôt.")); stop = true;
          }
        } catch (error) {
          if (!access || current !== epoch) return;
          row.result = "failed"; row.message = error.message;
          // Validation/conflicts are per spool; connection/authentication failures stop the queue.
          if (![409, 422, 404].includes(error.status)) stop = true;
        }
        render();
      }
      if (access && current === epoch) {
        text("result", stop ? msg("Envoi arrêté. Vérifiez à nouveau l’entrepôt pour traiter les bobines restantes.")
          : msg("Envoi terminé. Les fiches déjà présentes ont été conservées."));
        document.dispatchEvent(new CustomEvent("opt-station-inventory-updated"));
      }
    } finally { busy = false; sending = false; render(); }
  }
  $("open").addEventListener("click", () => {
    if (!access || busy) return;
    $("dialog").showModal();
    if (report) render(); else void check();
  });
  $("check").addEventListener("click", () => void check());
  $("send").addEventListener("click", () => void send());
  $("cancel").addEventListener("click", () => {
    stop = true; text("result", msg("Arrêt demandé après la vérification de la bobine en cours.")); controls();
  });
  $("close").addEventListener("click", () => { if (!busy) $("dialog").close(); });
  $("dialog").addEventListener("cancel", event => { if (busy) event.preventDefault(); });
  $("dialog").addEventListener("close", () => {
    stop = true;
    if (!report && !busy) { preview = null; rows = []; controls(); }
    void refreshSummary();
  });
  document.addEventListener("opt-station-status", event => {
    const next = Boolean(event.detail.access);
    if (next !== access) {
      access = next;
      if (!next) {
        epoch++; stop = true; preview = null; rows = []; report = false;
        invalidateSummary();
        $("dialog").close(); text("result", "");
      }
      render();
    }
    void refreshSummary();
  });
  document.addEventListener("opt-station-inventory-loaded", () => { invalidateSummary(); void refreshSummary(); });
  document.addEventListener("opt-station-tab", () => void refreshSummary());
  document.addEventListener("visibilitychange", () => void refreshSummary());
  document.addEventListener("opt-station-offline", () => {
    invalidateSummary(); summaryPhase = "error"; summaryAttempt = Date.now(); renderSummary();
  });
  document.addEventListener("opt-station-language", render);
  window.addEventListener("pagehide", () => {
    stop = true; epoch++;
    invalidateSummary();
    if (busy) {
      const interrupted = msg("Connexion interrompue. Vérifiez à nouveau l’entrepôt avant de reprendre ; aucun envoi n’est relancé automatiquement.");
      for (const row of rows) if (row.result === "sending") { row.result = "failed"; row.message = String(interrupted); }
      text("result", interrupted); sending = false;
    }
    // A cached page may be restored with an unfinished request. Never leave a
    // successful-looking preview or a permanently "sending" row behind.
    preview = null; render();
  });
  window.addEventListener("pageshow", () => { render(); void refreshSummary(); });
  controls();
})();
