"use strict";

(() => {
  const I18n = window.OPT_I18N, msg = I18n.msg;
  const $ = (id) => document.getElementById(id);
  let access = false, tab = "read", configuration = null, state = null;
  let dirty = false, busy = false, loading = false, polling = false, epoch = 0;
  let exportPreview = null, exportItem = null, exportValuesDirty = false, exportBusy = false, exportEpoch = 0;
  const text = (id, value) => I18n.text($(id), value ?? "—");
  const number = (value) => typeof value === "number" && Number.isFinite(value)
    ? new Intl.NumberFormat(I18n.locale(), {maximumFractionDigits: 1}).format(value) : "—";
  const statusText = (value) => ({
    updated: msg("Consommation actualisée"), unchanged: msg("Compteur déjà à jour"),
    ready: msg("Prête à actualiser"), unmatched: msg("Bobine absente de l’inventaire"),
    missing_identity: msg("Identité de bobine absente"), archived: msg("Archive conservée"),
    unsupported: msg("Matériau non pris en charge"), duplicate: msg("Identité ambiguë dans Connect"),
    manual_override: msg("Correction manuelle · synchronisation suspendue"),
    older_counter: msg("Compteur Connect plus ancien · fiche conservée"),
    rounded_counter: msg("Compteur Connect arrondi · précision locale conservée"),
    missing_weight: msg("Poids initial manquant"), weight_conflict: msg("Poids initial différent · fiche conservée"),
    invalid_counter: msg("Compteur incohérent · fiche conservée"), rfid_busy: msg("Écriture RFID en cours · fiche conservée")
  })[value] || msg("Vérification…");

  async function request(path, options = {}, raw = false) {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 60000);
    try {
      const response = await fetch(path, {credentials: "same-origin", cache: "no-store", signal: controller.signal,
        ...options, ...(options.body ? {headers: {"Content-Type": "application/json"}, body: JSON.stringify(options.body)} : {})});
      const value = await response.json();
      if (!response.ok) throw new Error(I18n.message(typeof value.detail === "string" ? value.detail : msg("Lecture Connect indisponible.")));
      return raw ? value : I18n.messages(value);
    } catch (error) {
      if (error.name === "AbortError") throw new Error(msg("Lecture Connect interrompue ou délai dépassé."));
      throw error;
    } finally { clearTimeout(timer); }
  }
  function sync() {
    $("connect-settings-fields").disabled = !access || !configuration || busy;
    ["connect-save", "connect-test", "connect-reload"].forEach((id) => { $(id).disabled = !access || !configuration || busy; });
    text("connect-access", access ? msg("Les accès Connect restent sur le Pi et ne sont jamais renvoyés au navigateur.") : msg("Activez l’accès complet pour configurer Prusa Connect."));
  }
  function options(id, items, current, empty) {
    const select = $(id);
    select.replaceChildren();
    const add = (value, label) => { const option = document.createElement("option"); option.value = value; option.textContent = label; select.append(option); };
    add("", empty);
    items.forEach((item) => add(item.id, item.name || item.id));
    if (current && !items.some((x) => x.id === current)) add(current, current);
    select.value = current || "";
  }
  function choices() {
    options("connect-organization", state?.teams || [], $("connect-organization").value,
      msg("Automatique si une seule organisation"));
    options("connect-printer", state?.printers || [], $("connect-printer").value,
      msg("Choisir l’imprimante après le test"));
  }
  function fill(value) {
    configuration = value;
    $("connect-enabled").checked = value.enabled;
    $("connect-sync-loaded").checked = value.sync_consumption;
    $("connect-sync-warehouse").checked = value.sync_warehouse;
    $("connect-interval").value = value.poll_seconds;
    $("connect-client-id").value = value.client_id;
    ["connect-access-token", "connect-refresh-token"].forEach((id) => { $(id).value = ""; });
    ["connect-clear-access", "connect-clear-refresh"].forEach((id) => { $(id).checked = false; });
    options("connect-organization", state?.teams || [], value.organization_id, msg("Automatique si une seule organisation"));
    options("connect-printer", state?.printers || [], value.printer_uuid, msg("Choisir l’imprimante après le test"));
    text("connect-token-state", value.access_token_saved ? msg("Secret enregistré; laisser vide pour le conserver.") : msg("Aucun secret enregistré."));
    text("connect-refresh-state", value.refresh_token_saved ? msg("Secret enregistré; laisser vide pour le conserver.") : msg("Aucun secret enregistré."));
    dirty = false; sync();
  }
  function render(value) {
    state = value;
    text("connect-state", value.connected ? msg("Connectée") : value.enabled ? msg("À vérifier") : msg("Désactivée"));
    text("printer-consumption-message", value.message);
    text("connect-updated", value.checked_at ? msg("Dernière lecture cloud : {0}", new Date(value.checked_at).toLocaleString(I18n.locale())) : "");
    $("connect-spools").replaceChildren();
    (value.spools || []).forEach((spool) => {
      const row = document.createElement("article"); row.className = "card-heading";
      const description = document.createElement("div"), title = document.createElement("strong"), details = document.createElement("p");
      title.textContent = [spool.spool_number, spool.name].filter(Boolean).join(" · ") || msg("Bobine non identifiée");
      I18n.text(details, msg("{0} g consommés · {1} g restants · {2}", number(spool.local_consumed_weight ?? spool.consumed_weight), number(spool.remaining_weight), statusText(spool.status)));
      details.className = "fine-print"; description.append(title, details); row.append(description);
      if (spool.status === "manual_override" && spool.inventory_id) {
        const button = document.createElement("button"); button.type = "button"; button.className = "button secondary";
        I18n.text(button, msg("Reprendre le compteur Connect")); button.disabled = !access || busy;
        button.addEventListener("click", async () => {
          if (!confirm(msg("Reprendre la consommation de cette bobine depuis Connect ? Les notes et données matériau sont conservées."))) return;
          button.disabled = true;
          try { await request(`/api/printer/connect/resume/${encodeURIComponent(spool.inventory_id)}`, {method: "POST", body: {version: spool.version}}); await poll(); }
          catch (error) { text("printer-consumption-message", error.message); }
          finally { button.disabled = !access; }
        }); row.append(button);
      }
      $("connect-spools").append(row);
    });
    text("connect-warehouse-summary", value.warehouse?.error ? value.warehouse.error : value.warehouse ? msg("Entrepôt Connect : {0} bobines · {1} reconnues dans OPT Station.", value.warehouse.total, value.warehouse.matched) : "");
    if (access && configuration) choices();
  }
  async function load() {
    if (!access || busy || loading) return;
    const current = epoch; loading = true;
    try { const value = await request("/api/configuration/connect"); if (access && current === epoch) fill(value); }
    catch (error) { if (access && current === epoch) text("connect-result", error.message); }
    finally { loading = false; sync(); }
  }
  async function poll() {
    if (!access || polling || !["printer", "configuration"].includes(tab) || document.visibilityState !== "visible") return;
    const current = epoch; polling = true;
    try { const value = await request("/api/printer/connect"); if (access && current === epoch) render(value); }
    catch (error) { if (access && current === epoch) text("printer-consumption-message", error.message); }
    finally { polling = false; }
  }
  async function save(test = false) {
    if (!access || busy || !configuration) return;
    const current = epoch;
    busy = true; sync(); text("connect-result", msg("Enregistrement des réglages…"));
    try {
      const body = {revision: configuration.revision, enabled: $("connect-enabled").checked,
        organization_id: $("connect-organization").value, printer_uuid: $("connect-printer").value,
        sync_consumption: $("connect-sync-loaded").checked, sync_warehouse: $("connect-sync-warehouse").checked,
        poll_seconds: Number($("connect-interval").value), client_id: $("connect-client-id").value.trim(),
        access_token: $("connect-access-token").value.trim() || null, refresh_token: $("connect-refresh-token").value.trim() || null,
        clear_access_token: $("connect-clear-access").checked, clear_refresh_token: $("connect-clear-refresh").checked};
      const record = await request("/api/configuration/connect", {method: "PUT", body});
      if (!access || current !== epoch) return;
      fill(record);
      if (test) {
        text("connect-result", msg("Lecture de Connect et de l’entrepôt…"));
        const result = await request("/api/printer/connect/test", {method: "POST", body: {}});
        if (!access || current !== epoch) return;
        render(result); text("connect-result", result.message);
      } else text("connect-result", msg("Réglages Connect enregistrés. La lecture continue sur le Pi."));
    } catch (error) { if (access && current === epoch) text("connect-result", error.message); }
    finally { busy = false; sync(); }
  }
  document.addEventListener("opt-station-status", (event) => {
    const next = Boolean(event.detail.access);
    if (access && !next) {
      epoch++; configuration = null; state = null; dirty = false;
      ["connect-access-token", "connect-refresh-token", "connect-client-id"].forEach((id) => { $(id).value = ""; });
      $("connect-organization").replaceChildren(); $("connect-printer").replaceChildren();
      $("connect-spools").replaceChildren(); text("connect-result", ""); text("connect-updated", ""); text("connect-warehouse-summary", "");
      $("connect-info-dialog").close();
      exportEpoch++; exportPreview = null; exportItem = null; exportValuesDirty = false;
      $("connect-export-dialog").close(); $("connect-export-summary").replaceChildren();
      $("connect-export-values-form").reset();
    }
    const gained = next && !access; access = next; sync();
    if (access && tab === "configuration" && (gained || !configuration)) void load();
    if (gained) void poll();
  });
  document.addEventListener("opt-station-tab", (event) => {
    tab = event.detail.tab;
    if (tab === "configuration" && access && !configuration) void load();
    void poll();
  });
  $("connect-settings-form").addEventListener("input", () => { dirty = true; text("connect-result", msg("Modifications à enregistrer.")); });
  $("connect-settings-form").addEventListener("change", (event) => {
    dirty = true;
    if (event.target.id === "connect-organization") {
      options("connect-printer", [], "", msg("Choisir l’imprimante après le test"));
      if (state) state.printers = [];
    }
  });
  $("connect-settings-form").addEventListener("submit", (event) => { event.preventDefault(); void save(); });
  $("connect-test").addEventListener("click", () => void save(true));
  $("connect-reload").addEventListener("click", () => {
    if (!dirty || confirm(msg("Recharger les réglages du Pi et abandonner les modifications non enregistrées ?"))) void load();
  });
  $("connect-info").addEventListener("click", () => $("connect-info-dialog").showModal());
  function exportControls() {
    $("connect-export-send").disabled = !access || exportBusy || exportValuesDirty || !exportPreview;
    $("connect-export-values-fields").disabled = !access || exportBusy || !exportItem;
    $("connect-export-values-save").disabled = !access || exportBusy || !exportItem;
  }
  async function loadExportPreview(current) {
    const item = exportItem;
    exportPreview = null;
    text("connect-export-result", msg("Vérification de la bobine dans l’entrepôt…"));
    try {
      const value = await request(`/api/inventory/${encodeURIComponent(item.id)}/connect/preview`, {method: "POST", body: {version: item.version, notes_revision: item.notes_revision}}, true);
      if (!access || current !== exportEpoch) return;
      exportPreview = {...value, inventory_id: item.id};
      const summary = document.createElement("dl"); summary.className = "key-values connect-export-summary";
      for (const [label, entry] of [[msg("Bobine"), value.name], [msg("Organisation Connect"), value.organization],
        [msg("Poids net initial"), number(value.initial_weight) + " g"], [msg("Consommé"), number(value.consumed_weight) + " g"],
        [msg("Restant connu"), number(value.remaining_weight) + " g"], [msg("Notes de cette bobine"), value.notes || "—"]]) {
        const row = document.createElement("div"), term = document.createElement("dt"), description = document.createElement("dd");
        I18n.text(term, label); description.textContent = entry; row.append(term, description); summary.append(row);
      }
      $("connect-export-summary").replaceChildren(summary);
      text("connect-export-result", value.disposition === "repair" ? msg("La bobine existe déjà. Sa référence de matériau sera enregistrée pour la rendre visible dans l’entrepôt, sans recréer la bobine.") : value.disposition === "present" ? msg("Cette bobine existe déjà dans Connect. Aucune nouvelle fiche ne sera créée.") : value.disposition === "resume" ? msg("Un envoi précédent sera vérifié et terminé sans nouvelle création.") : msg("Une nouvelle fiche sera créée dans l’entrepôt sélectionné."));
      I18n.text($("connect-export-send"), value.disposition === "repair" ? msg("Rendre la bobine visible") : value.disposition === "present" ? msg("Vérifier la présence") : value.disposition === "resume" ? msg("Terminer l’envoi") : msg("Envoyer cette bobine"));
    } catch (error) {
      if (access && current === exportEpoch) { text("connect-export-result", error.message); $("connect-export-correction").open = true; }
    }
  }
  window.OPT_CONNECT_EXPORT = {open: async (item) => {
    if (!access || exportBusy) return;
    const current = ++exportEpoch;
    exportItem = item; exportPreview = null; exportValuesDirty = false; exportBusy = true;
    $("connect-export-nominal").value = item.main.nominal_netto_full_weight ?? "";
    $("connect-export-actual").value = item.main.actual_netto_full_weight ?? "";
    $("connect-export-consumed").value = item.aux.consumed_weight ?? "";
    $("connect-export-correction").open = false;
    I18n.text($("connect-export-send"), msg("Envoyer cette bobine"));
    exportControls(); $("connect-export-summary").replaceChildren(); $("connect-export-dialog").showModal();
    try { await loadExportPreview(current); }
    finally { exportBusy = false; exportControls(); }
  }};
  $("connect-export-values-form").addEventListener("input", () => {
    exportValuesDirty = true; exportPreview = null; exportControls();
    text("connect-export-result", msg("Enregistrez les valeurs avant l’envoi vers Connect."));
  });
  $("connect-export-values-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!access || exportBusy || !exportItem || !event.currentTarget.reportValidity()) return;
    const current = exportEpoch;
    exportBusy = true; exportControls();
    try {
      const result = await request(`/api/inventory/${encodeURIComponent(exportItem.id)}/connect/values`, {method: "POST", body: {
        version: exportItem.version, nominal_initial_weight: Number($("connect-export-nominal").value),
        actual_initial_weight: $("connect-export-actual").value === "" ? null : Number($("connect-export-actual").value),
        consumed_weight: Number($("connect-export-consumed").value)}}, true);
      if (!access || current !== exportEpoch) return;
      exportItem = result.item; exportValuesDirty = false;
      document.dispatchEvent(new CustomEvent("opt-station-inventory-updated"));
      await loadExportPreview(current);
    } catch (error) { if (access && current === exportEpoch) text("connect-export-result", error.message); }
    finally { exportBusy = false; exportControls(); }
  });
  $("connect-export-send").addEventListener("click", async () => {
    if (!access || exportBusy || !exportPreview) return;
    const current = exportEpoch, preview = exportPreview;
    exportBusy = true; exportControls(); text("connect-export-result", msg("Envoi et relecture dans Prusa Connect…"));
    try {
      const result = await request(`/api/inventory/${encodeURIComponent(preview.inventory_id)}/connect/export`, {method: "POST", body: {version: preview.version, notes_revision: preview.notes_revision, fingerprint: preview.fingerprint}}, true);
      if (!access || current !== exportEpoch) return;
      exportPreview = null;
      text("connect-export-result", result.differences.length ? msg("La bobine existe déjà, avec des données différentes. Sa fiche Connect est conservée.") : result.status === "repaired" ? msg("Bobine visible dans l’entrepôt Connect. Aucun doublon n’a été créé.") : result.created ? msg("Bobine envoyée et relue dans Connect. Son identité et ses quantités sont vérifiées.") : msg("Présence de la bobine confirmée. Aucun doublon n’a été créé."));
      void poll();
    } catch (error) {
      if (access && current === exportEpoch) { exportPreview = null; text("connect-export-result", error.message); }
    } finally { exportBusy = false; exportControls(); }
  });
  $("connect-export-dialog").addEventListener("close", () => {
    exportEpoch++; exportPreview = null; exportItem = null; exportValuesDirty = false;
    $("connect-export-values-form").reset(); exportControls();
  });
  document.addEventListener("opt-station-language", () => { sync(); if (state && access) render(state); });
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") void poll(); });
  const timer = setInterval(() => void poll(), 10000);
  window.addEventListener("pagehide", () => { epoch++; clearInterval(timer); });
  sync();
})();
