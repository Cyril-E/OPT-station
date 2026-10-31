"use strict";
(() => {
  const I18n = window.OPT_I18N; I18n.init();
  const msg = I18n.msg, $ = id => document.getElementById(id);
  const text = (id, value) => I18n.text($(id), I18n.message(value));
  let status = null, configuration = null, access = false, busy = false, pendingPower = false, dirty = false, tab = 'read';
  const date = value => value ? new Date(value).toLocaleString(I18n.locale()) : msg("Jamais");
  function render() {
    const available = Boolean(status?.enabled && status?.update_available && status?.latest?.url);
    $("updates-banner").hidden = $("updates-sidebar").hidden = !available;
    $("updates-release-link").hidden = !status?.latest?.url;
    $("updates-notes-open").hidden = !status?.latest?.url;
    if (status?.latest?.url) ["updates-banner-link", "updates-release-link", "updates-notes-link"].forEach(id => { $(id).href = status.latest.url; });
    else ["updates-banner-link", "updates-release-link", "updates-notes-link"].forEach(id => $(id).removeAttribute('href'));
    // GitHub content stays plain text, in the language used by its author.
    $("updates-notes-version").textContent = status?.latest?.name || status?.latest?.tag || "";
    $("updates-notes-content").textContent = status?.latest?.notes || msg("Aucun détail n’a été fourni pour cette version. Consultez sa page GitHub.");
    if (!status?.latest?.url && $("updates-notes-dialog").open) $("updates-notes-dialog").close();
    if (available) text("updates-banner-text", msg("Version {0} disponible · version installée : {1}", status.latest.tag, status.installed_version));
    text("updates-installed", status?.installed_version || "—"); text("updates-latest", status?.latest?.tag || "—");
    let label = msg("À vérifier"), message = msg("Activez la recherche de versions pour consulter les publications GitHub.");
    if (status) {
      if (!status.enabled) { label = msg("Désactivée"); message = msg("La recherche automatique de versions est désactivée."); }
      else if (status.checking) { label = msg("Vérification…"); message = msg("Vérification des versions publiées sur GitHub…"); }
      else if (status.error_code) { label = status.error_code === 'access' || status.error_code === 'token' ? msg("Accès GitHub requis") : msg("Vérification indisponible"); message = I18n.message(status.message); }
      else if (status.phase === 'ok') {
        if (available) { label = msg("Mise à jour disponible"); message = msg("La version {0} est disponible. Consultez ses nouveautés ici ou sur GitHub.", status.latest.tag); }
        else if (!status.latest) { label = msg("Aucune version compatible"); message = msg("Aucune publication compatible avec les options choisies n’a été trouvée."); }
        else if (status.comparison === 'ahead') { label = msg("Version plus récente installée"); message = msg("La version installée est plus récente que la dernière publication GitHub ({0}).", status.latest.tag); }
        else { label = msg("À jour"); message = msg("La station utilise la dernière version publiée compatible avec vos options."); }
      }
    }
    text("updates-state", label); text("updates-status-message", message);
    text("updates-dates", status?.enabled ? msg("Dernier contrôle réussi : {0} · prochaine vérification : {1}", date(status.checked_at), date(status.next_check_at)) : "");
    const cooling = Boolean(status?.retry_allowed_at && Date.parse(status.retry_allowed_at) > Date.now());
    $("updates-fields").disabled = !access || busy || pendingPower;
    $("updates-save").disabled = !access || busy || pendingPower || !configuration;
    $("updates-reload").disabled = !access || busy;
    $("updates-check").disabled = !access || busy || pendingPower || dirty || !status?.enabled || status.checking || cooling;
    text("updates-access", access ? configuration?.token_saved ? msg("Un jeton GitHub est enregistré sur le Pi. Il n’est pas affiché ici.") : msg("Aucun jeton GitHub enregistré. Le dépôt public peut être consulté sans jeton.") : msg("Les réglages GitHub nécessitent l’accès local ou complet."));
  }
  async function request(url, body, method = 'POST') {
    const response = await fetch(url, {method: body === undefined ? 'GET' : method, cache:'no-store', credentials:'same-origin', signal:AbortSignal.timeout(10000), ...(body === undefined ? {} : {headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})});
    const result = await response.json();
    if (!response.ok) throw new Error(I18n.message(result.detail || msg("Vérification GitHub indisponible.")));
    return result;
  }
  function fill() {
    if (!configuration) return;
    $("updates-enabled").checked = configuration.enabled; $("updates-repository").value = configuration.repository;
    $("updates-interval").value = configuration.interval_hours; $("updates-prereleases").checked = configuration.include_prereleases;
    $("updates-token").value = ""; $("updates-clear-token").checked = false; dirty = false;
  }
  async function refresh() {
    if (!access || busy) return;
    busy = true; render();
    try { configuration = await request('/api/configuration/updates'); status = configuration.status; fill(); text("updates-result", msg("Réglages GitHub chargés depuis le Pi.")); }
    catch (error) { text("updates-result", error.message); }
    finally { busy = false; render(); }
  }
  $("updates-form").addEventListener('input', () => { dirty = true; render(); });
  $("updates-form").addEventListener('submit', async event => {
    event.preventDefault(); if (!configuration || !access || busy || pendingPower) return;
    busy = true; render();
    try {
      configuration = await request('/api/configuration/updates', {revision:configuration.revision, enabled:$("updates-enabled").checked,
        repository:$("updates-repository").value.trim(), interval_hours:Number($("updates-interval").value), include_prereleases:$("updates-prereleases").checked,
        token:$("updates-token").value || null, clear_token:$("updates-clear-token").checked}, 'PUT');
      status = configuration.status; fill(); text("updates-result", msg("Recherche de versions enregistrée. La première vérification sera lancée si elle est activée."));
    } catch (error) { text("updates-result", error.message); }
    finally { busy = false; render(); }
  });
  $("updates-reload").addEventListener('click', refresh);
  $("updates-check").addEventListener('click', async () => {
    if (!access || busy || dirty || pendingPower) return;
    busy = true; render();
    try { status = await request('/api/updates/check', {}); text("updates-result", msg("Vérification GitHub demandée. Le résultat apparaîtra dans quelques instants.")); }
    catch (error) { text("updates-result", error.message); }
    finally { busy = false; render(); }
  });
  $("updates-info").addEventListener('click', () => $("updates-info-dialog").showModal());
  function showNotes() {
    if (!status?.latest?.url || $("updates-notes-dialog").open) return;
    $("updates-notes-dialog").showModal();
  }
  ["updates-sidebar", "updates-banner-notes", "updates-notes-open"].forEach(id => $(id).addEventListener('click', showNotes));
  document.addEventListener('opt-station-status', event => {
    access = event.detail.access; pendingPower = Boolean(event.detail.power?.pending); status = event.detail.updates;
    if (!access) { configuration = null; $("updates-token").value = ""; dirty = false; }
    else if (tab === 'configuration' && !dirty && configuration?.revision !== status?.revision) refresh();
    render();
  });
  document.addEventListener('opt-station-tab', event => { tab = event.detail.tab; if (tab === 'configuration' && !dirty) refresh(); });
  document.addEventListener('opt-station-language', render); render();
})();
