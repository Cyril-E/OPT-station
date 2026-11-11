"use strict";

(() => {
  const I18N = window.OPT_I18N, msg = I18N.msg;
  const $ = name => document.getElementById("screen-sleep-" + name);
  let access = false, powerPending = false, busy = false, tab = "inventory";
  let configuration = null, generation = 0;
  function message(value) { I18N.text($("message"), I18N.message(value)); }
  function render() {
    const blocked = !access || powerPending || busy;
    $("fields").disabled = blocked || !configuration?.supported;
    $("refresh").disabled = blocked;
    $("wake").disabled = blocked || !configuration?.supported;
    I18N.text($("state"), !configuration?.supported ? msg("Indisponible")
      : !configuration.timeout_minutes ? msg("Désactivée") : configuration.running ? msg("Activée") : msg("En attente"));
  }
  async function request(method, body, suffix = "") {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch("/api/configuration/screen" + suffix, {method, cache: "no-store", credentials: "same-origin", signal: controller.signal,
        ...(body ? {headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)} : {})});
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "");
      return result;
    } finally { clearTimeout(timer); }
  }
  function receive(result) {
    configuration = result;
    $("timeout").value = String(result.timeout_minutes);
    message(result.message);
  }
  async function refresh() {
    if (!access || powerPending || busy) return;
    const current = ++generation;
    busy = true; render();
    try { const result = await request("GET"); if (current === generation) receive(result); }
    catch (_) { if (current === generation) { configuration = null; message(msg("Impossible de lire la veille de l’écran. Actualisez pour réessayer.")); } }
    finally { if (current === generation) { busy = false; render(); } }
  }
  async function perform(wake) {
    if (!access || powerPending || busy || !configuration?.supported) return;
    const current = ++generation;
    const body = wake ? {} : {revision: configuration.revision, timeout_minutes: Number($("timeout").value)};
    busy = true; render();
    try {
      const result = await request(wake ? "POST" : "PUT", body, wake ? "/wake" : "");
      if (current === generation) { if (wake) message(result.message); else receive(result); }
    } catch (error) {
      if (current === generation) {
        configuration = null;
        message(error.name === "AbortError" || error instanceof TypeError || !error.message
          ? msg("Le résultat n’a pas pu être vérifié. Actualisez la veille avant de réessayer.") : error.message);
      }
    } finally { if (current === generation) { busy = false; render(); } }
  }
  $("form").addEventListener("submit", event => { event.preventDefault(); void perform(false); });
  $("refresh").addEventListener("click", () => void refresh());
  $("wake").addEventListener("click", () => void perform(true));
  document.addEventListener("opt-station-status", event => {
    const wasAvailable = access && !powerPending;
    access = Boolean(event.detail.access); powerPending = Boolean(event.detail.power?.pending);
    if (!access || powerPending) {
      generation++; busy = false; configuration = null;
      message(msg("L’accès local ou complet est nécessaire pour régler la veille de l’écran."));
    } else if (!wasAvailable && tab === "configuration") void refresh();
    render();
  });
  document.addEventListener("opt-station-tab", event => { tab = event.detail.tab; if (tab === "configuration") void refresh(); });
  document.addEventListener("opt-station-offline", () => {
    generation++; access = false; busy = false; configuration = null;
    message(msg("La station est hors ligne. La veille de l’écran n’a pas été vérifiée.")); render();
  });
  document.addEventListener("opt-station-language", render);
  render();
})();
