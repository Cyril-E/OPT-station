"use strict";

(() => {
  const I18N = window.OPT_I18N, msg = I18N.msg;
  const $ = name => document.getElementById("touchscreen-" + name);
  let access = false, powerPending = false, tab = "inventory", busy = false;
  let configuration = null, generation = 0;

  function message(value) { I18N.text($("message"), I18N.message(value)); }

  function render() {
    $("fields").disabled = !access || powerPending || busy || !configuration?.supported;
    $("refresh").disabled = !access || powerPending || busy;
    const state = !configuration?.supported ? msg("Indisponible")
      : configuration.mixed ? msg("Modes tactiles différents")
      : configuration.enabled ? msg("Activé") : msg("Désactivé");
    I18N.text($("state"), state);
    $("devices").textContent = configuration?.devices.join(", ") || "";
  }

  async function request(method, body) {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch("/api/configuration/touchscreen", {method, credentials: "same-origin", cache: "no-store",
        signal: controller.signal, ...(body ? {headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)} : {})});
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "");
      return result;
    } finally { clearTimeout(timer); }
  }

  function receive(value) {
    configuration = value;
    $("enabled").checked = Boolean(value.enabled);
    $("enabled").indeterminate = Boolean(value.mixed);
    message(value.message);
  }

  async function refresh() {
    if (!access || powerPending || busy) return;
    const current = ++generation;
    busy = true; render();
    message(msg("Vérification du mode tactile…"));
    try {
      const result = await request("GET");
      if (current === generation) receive(result);
    } catch (_) {
      if (current === generation) {
        configuration = null;
        message(msg("Impossible de lire le mode tactile. Actualisez pour réessayer."));
      }
    } finally { if (current === generation) { busy = false; render(); } }
  }

  $("form").addEventListener("submit", async event => {
    event.preventDefault();
    if (!access || powerPending || busy || !configuration?.supported) return;
    const current = ++generation, body = {revision: configuration.revision, enabled: $("enabled").checked};
    busy = true; render();
    message(msg("Enregistrement du mode tactile…"));
    try {
      const result = await request("PUT", body);
      if (current === generation) receive(result);
    } catch (error) {
      if (current === generation) {
        configuration = null;
        message(error.name === "AbortError" || error instanceof TypeError || !error.message
          ? msg("Le résultat n’a pas pu être vérifié. Actualisez le mode tactile avant de réessayer.") : error.message);
      }
    } finally { if (current === generation) { busy = false; render(); } }
  });
  $("enabled").addEventListener("change", () => { $("enabled").indeterminate = false; });
  $("refresh").addEventListener("click", () => void refresh());
  document.addEventListener("opt-station-status", event => {
    const wasAvailable = access && !powerPending;
    access = Boolean(event.detail.access);
    powerPending = Boolean(event.detail.power?.pending);
    if (!access || powerPending) {
      generation++; busy = false; configuration = null;
      message(msg("L’accès local ou complet est nécessaire pour régler le tactile du Pi."));
    } else if (!wasAvailable && tab === "configuration") void refresh();
    render();
  });
  document.addEventListener("opt-station-tab", event => {
    tab = event.detail.tab;
    if (tab === "configuration") void refresh();
  });
  document.addEventListener("opt-station-offline", () => {
    generation++; access = false; busy = false; configuration = null;
    message(msg("La station est hors ligne. Le mode tactile n’a pas été vérifié.")); render();
  });
  document.addEventListener("opt-station-language", render);
  render();
})();
