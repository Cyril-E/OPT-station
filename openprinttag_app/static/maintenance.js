"use strict";

(() => {
  const I18n = window.OPT_I18N; I18n.init();
  const msg = I18n.msg, $ = (id) => document.getElementById(id);
  let access = false, browse = false, pendingPower = false, busy = false, tab = "read";
  let configuration = null, dirty = false, importPreview = null, restorePreview = null;
  const text = (id, value) => I18n.text($(id), I18n.message(value));
  const date = (value) => value ? new Date(value).toLocaleString(I18n.locale()) : msg("Jamais");
  const element = (tag, content) => { const el = document.createElement(tag); if (content !== undefined) I18n.text(el, content); return el; };
  async function request(url, body, method = "POST", raw = false) {
    const response = await fetch(url, {method: body === undefined ? "GET" : method, cache: "no-store", credentials: "same-origin", signal: AbortSignal.timeout(120000),
      ...(body === undefined ? {} : {headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)})});
    if (!response.ok) {
      const result = await response.json();
      throw new Error(I18n.message(result.detail || msg("Opération indisponible.")));
    }
    return raw ? response : response.json();
  }
  function download(blob, name) {
    const link = document.createElement("a"), url = URL.createObjectURL(blob);
    link.href = url; link.download = name; document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
  }
  function render() {
    $("backups-fields").disabled = !access || busy || pendingPower;
    $("backups-reload").disabled = !access || busy;
    $("library-export-open").disabled = $("library-import-open").disabled = !browse || busy || pendingPower;
    $("library-export-download").disabled = $("library-import-preview").disabled = !browse || busy || pendingPower;
    $("library-import-confirm").disabled = !browse || busy || pendingPower || !importPreview;
    $("backup-restore-confirm").disabled = !access || busy || pendingPower || !restorePreview || !$("backup-restore-ack").checked;
    $("backup-run").disabled = busy || dirty || (configuration?.encrypted !== false && !configuration?.password_saved) || !configuration?.destination;
    const protect = $("backup-protected").checked, automatic = $("backup-encrypted").checked;
    $("backup-password-fields").hidden = !protect;
    for (const id of ["backup-password", "backup-password-confirm"]) { $(id).disabled = !protect; $(id).required = protect; }
    $("backup-auto-password-field").hidden = !automatic;
    $("backup-auto-password-note").hidden = !automatic;
    $("backup-auto-password").disabled = !automatic;
    $("backup-auto-password").required = automatic && $("backup-enabled").checked && !configuration?.password_saved;
    text("backups-access", access ? msg("Téléchargez une copie avec ou sans mot de passe, ou restaurez un fichier après vérification.") : msg("Les sauvegardes et restaurations nécessitent l’accès local ou complet."));
    $("backup-point-preview").disabled = !access || busy || pendingPower || !configuration?.restore_points?.length;
    if (configuration) {
      const points = $("backup-point"), selected = points.value;
      points.replaceChildren();
      for (const point of configuration.restore_points || []) { const option = element("option", `${date(point.created_at)} · ${point.id.slice(0, 8)}`); option.value = point.id; points.append(option); }
      if ((configuration.restore_points || []).some(point => point.id === selected)) points.value = selected;
      const last = configuration.last_result || {};
      text("backup-next", configuration.enabled ? msg("Prochaine sauvegarde : {0}", date(configuration.next_run)) : msg("Planification désactivée."));
      text("backup-last", last.attempted_at ? msg("Dernier essai : {0} · {1}", date(last.attempted_at), I18n.message(last.message)) : msg("Aucune sauvegarde automatique effectuée."));
    }
  }
  async function action(resultId, operation) {
    if (busy || pendingPower) return;
    busy = true; render(); text(resultId, msg("Opération en cours…"));
    try { await operation(); }
    catch (error) { text(resultId, error.message || msg("La station est injoignable.")); }
    finally { busy = false; render(); }
  }
  function fillVolumes(selected) {
    if (!configuration) return;
    const c = configuration, select = $("backup-volume"); select.replaceChildren();
    const empty = element("option", msg("Choisir un support monté")); empty.value = ""; select.append(empty);
    for (const volume of c.volumes) {
      const option = element("option", volume.writable ? volume.path : msg("{0} · lecture seule", volume.path));
      option.value = volume.path; option.disabled = !volume.writable;
      select.append(option);
    }
    if (selected && !c.volumes.some(v => v.path === selected)) {
      const absent = element("option", msg("{0} · absent", selected)); absent.value = selected; select.append(absent);
    }
    select.value = selected;
  }
  function fillSchedule() {
    if (!configuration) return;
    const c = configuration; fillVolumes(c.mount_path);
    $("backup-enabled").checked = c.enabled;
    $("backup-encrypted").checked = c.encrypted ?? true;
    $("backup-folder").value = c.destination && c.mount_path ? c.destination.slice(c.mount_path.length).replace(/^\/+/, "") : "opt-station-backups";
    $("backup-frequency").value = c.frequency; $("backup-weekday").value = c.weekday;
    $("backup-time").value = c.time; $("backup-timezone").value = c.timezone; $("backup-keep").value = c.keep;
    $("backup-auto-password").value = ""; dirty = false;
  }
  async function refresh() {
    if (!access || busy) return;
    await action("backups-result", async () => {
      const selected = $("backup-volume").value;
      configuration = await request("/api/configuration/backups");
      if (!dirty) fillSchedule(); else fillVolumes(selected);
      text("backups-result", msg("Réglages et supports de sauvegarde actualisés."));
    });
  }
  $("backups-reload").addEventListener("click", refresh);
  $("backup-protected").addEventListener("change", () => {
    if (!$("backup-protected").checked) $("backup-password").value = $("backup-password-confirm").value = "";
    render();
  });
  $("backup-schedule-form").addEventListener("input", () => { dirty = true; render(); });
  $("backup-schedule-form").addEventListener("submit", event => {
    event.preventDefault(); if (!configuration || !access) return;
    action("backups-result", async () => {
      const mount = $("backup-volume").value, folder = $("backup-folder").value.trim();
      const volume = configuration.volumes.find(v => v.path === mount);
      if (folder.startsWith("/") || folder.split("/").some(p => p === ".." || p === ".") || !folder) throw new Error(msg("Indiquez un sous-dossier du support choisi."));
      configuration = await request("/api/configuration/backups", {revision: configuration.revision, enabled: $("backup-enabled").checked, encrypted: $("backup-encrypted").checked,
        destination: mount ? mount.replace(/\/$/, "") + "/" + folder : "", mount_path: mount, mount_source: volume?.source || configuration.mount_source || "",
        frequency: $("backup-frequency").value, time: $("backup-time").value, weekday: Number($("backup-weekday").value), timezone: $("backup-timezone").value.trim(),
        keep: Number($("backup-keep").value), password: $("backup-encrypted").checked ? $("backup-auto-password").value || null : null}, "PUT");
      fillSchedule(); text("backups-result", msg("Planification enregistrée sur le Pi."));
    });
  });
  $("backup-run").addEventListener("click", () => action("backups-result", async () => {
    configuration = await request("/api/backups/run", {});
    text("backups-result", configuration.last_result?.message || msg("Sauvegarde enregistrée et vérifiée."));
  }));
  $("backup-download").addEventListener("click", () => action("backups-result", async () => {
    const protect = $("backup-protected").checked;
    const password = protect ? $("backup-password").value : null;
    if (protect && password.length < 10) throw new Error(msg("Choisissez un mot de passe de sauvegarde de 10 à 256 caractères."));
    if (protect && password !== $("backup-password-confirm").value) throw new Error(msg("Les deux mots de passe ne correspondent pas."));
    const scope = $("backup-scope").value;
    const response = await request("/api/backups/download", {scope, password}, "POST", true);
    download(await response.blob(), `opt-station-${scope}-${new Date().toISOString().slice(0, 10)}.optbak`);
    $("backup-password").value = $("backup-password-confirm").value = "";
    text("backups-result", protect ? msg("Sauvegarde téléchargée. Conservez son mot de passe séparément.") : msg("Sauvegarde téléchargée sans mot de passe."));
  }));
  $("backup-preview").addEventListener("click", () => action("backups-result", async () => {
    restorePreview = null;
    const file = $("restore-file").files[0];
    if (!file || file.size > 32 * 1024 * 1024) throw new Error(msg("Sélectionnez une sauvegarde OPT Station de 32 Mo maximum."));
    const bytes = new Uint8Array(await file.arrayBuffer());
    const chunks = []; for (let i = 0; i < bytes.length; i += 8192) chunks.push(String.fromCharCode(...bytes.subarray(i, i + 8192)));
    const preview = await request("/api/backups/restore/preview", {content: btoa(chunks.join("")), password: $("restore-password").value});
    $("restore-password").value = ""; showRestore(preview);
  }));
  function showRestore(preview) {
    restorePreview = preview;
    const summary = $("backup-restore-summary"); summary.replaceChildren();
    summary.append(element("p", msg("Sauvegarde du {0} · version {1}", date(preview.created_at), preview.application_version)));
    summary.append(element("strong", {all: msg("Configuration et inventaire"), inventory: msg("Inventaire et bibliothèque"), configuration: msg("Configuration uniquement")}[preview.scope]));
    if (preview.spools !== undefined) summary.append(element("p", msg("{0} bobine(s), dont {1} terminée(s), et {2} fiche(s) de bibliothèque.", preview.spools, preview.completed, preview.templates)));
    if (preview.configuration_files) summary.append(element("p", msg("{0} fichier(s) de configuration, avec les identifiants enregistrés.", preview.configuration_files.length)));
    $("backup-restore-ack").checked = false; text("backup-restore-result", "");
    $("backup-restore-dialog").showModal(); text("backups-result", msg("Sauvegarde vérifiée. Confirmez son contenu dans la fenêtre."));
  }
  $("backup-point-preview").addEventListener("click", () => action("backups-result", async () => {
    if (!$("backup-point").value) throw new Error(msg("Point de retour introuvable."));
    const preview = await request(`/api/backups/points/${encodeURIComponent($("backup-point").value)}/preview`, {});
    showRestore(preview);
  }));
  $("backup-restore-ack").addEventListener("change", render);
  $("backup-restore-dialog").addEventListener("close", () => { restorePreview = null; render(); });
  $("backup-restore-dialog").addEventListener("cancel", event => { if (busy) event.preventDefault(); });
  $("backup-restore-confirm").addEventListener("click", () => {
    if (!restorePreview || !$("backup-restore-ack").checked) return;
    const token = restorePreview.preview_id;
    action("backup-restore-result", async () => {
      const result = await request("/api/backups/restore/commit", {preview_id: token, confirmed: true});
      restorePreview = null;
      text("backup-restore-result", msg("Restauration terminée. Point de retour : {0}. Rechargement de l’interface…", result.rollback_point));
      setTimeout(() => window.location.reload(), 1800);
    });
  });
  $("library-export-open").addEventListener("click", () => {
    $("library-export-dialog").showModal();
    action("library-export-result", async () => {
      const items = (await request("/api/favorites")).items, list = $("library-export-items"); list.replaceChildren();
      for (const item of items) {
        const row = element("div"), label = element("label"), input = element("input"), name = element("strong");
        row.className = "transfer-item"; input.type = "checkbox"; input.value = item.id; input.checked = true;
        // Library names are data; never register them as translatable messages.
        name.textContent = item.name;
        label.append(input, name); row.append(label, element("span", item.kind === "model" ? msg("Modèle de bobine") : msg("Favori"))); list.append(row);
      }
      text("library-export-result", items.length ? msg("{0} fiche(s) disponible(s).", items.length) : msg("Aucune fiche à exporter."));
    });
  });
  $("library-select-all").addEventListener("click", () => $("library-export-items").querySelectorAll("input").forEach(el => { el.checked = true; }));
  $("library-select-none").addEventListener("click", () => $("library-export-items").querySelectorAll("input").forEach(el => { el.checked = false; }));
  $("library-export-download").addEventListener("click", () => action("library-export-result", async () => {
    const identifiers = Array.from($("library-export-items").querySelectorAll("input:checked"), el => el.value);
    if (!identifiers.length) throw new Error(msg("Sélectionnez au moins une fiche à exporter."));
    const response = await request("/api/library/export", {identifiers}, "POST", true);
    download(await response.blob(), "opt-station-library.json"); text("library-export-result", msg("Fiches exportées. Ce fichier peut être importé dans une autre station."));
  }));
  $("library-import-open").addEventListener("click", () => { importPreview = null; $("library-import-file").value = ""; $("library-import-items").replaceChildren(); text("library-import-result", ""); $("library-import-dialog").showModal(); render(); });
  $("library-import-file").addEventListener("change", () => { importPreview = null; $("library-import-items").replaceChildren(); render(); });
  $("library-import-preview").addEventListener("click", () => action("library-import-result", async () => {
    importPreview = null;
    const file = $("library-import-file").files[0];
    if (!file || file.size > 1000000) throw new Error(msg("Sélectionnez un fichier de bibliothèque JSON de 1 Mo maximum."));
    const preview = await request("/api/library/import/preview", {document: await file.text()});
    importPreview = preview;
    const list = $("library-import-items"); list.replaceChildren();
    for (const item of preview.items) {
      const row = element("div"), name = element("strong"), select = element("select"); row.className = "transfer-item"; row.dataset.index = item.index; name.textContent = item.name;
      const choice = element("label", msg("Choix d’import")); choice.className = "field";
      const options = item.existing ? [["skip", msg("Conserver la fiche existante")], ["rename", msg("Importer sous un autre nom")], ...(item.existing.kind === item.kind ? [["replace", msg("Remplacer la fiche existante")]] : [])] : [["create", msg("Créer cette fiche")], ["skip", msg("Ignorer cette fiche")]];
      for (const [value, label] of options) { const option = element("option", label); option.value = value; select.append(option); }
      choice.append(select); const rename = element("input"); rename.type = "text"; rename.maxLength = 120; rename.value = item.name; rename.hidden = true;
      I18n.attribute(rename, "aria-label", msg("Nouveau nom de la fiche"));
      select.addEventListener("change", () => { rename.hidden = select.value !== "rename"; });
      const details = element("details"), values = element("pre"); details.append(element("summary", msg("Voir les données de la fiche"))); values.textContent = JSON.stringify(item.main, null, 2); details.append(values);
      row.append(name, element("p", item.existing ? item.identical ? msg("Fiche identique déjà présente.") : msg("Un nom identique existe déjà dans la bibliothèque.") : msg("Nouvelle fiche.")), choice, rename, details); list.append(row);
    }
    text("library-import-result", msg("Vérifiez les fiches et les choix avant de confirmer l’import."));
  }));
  $("library-import-confirm").addEventListener("click", () => action("library-import-result", async () => {
    if (!importPreview) return;
    const choices = Array.from($("library-import-items").children, row => ({index: Number(row.dataset.index), action: row.querySelector("select").value, name: row.querySelector("input").value}));
    const result = await request("/api/library/import/commit", {preview_id: importPreview.preview_id, choices});
    importPreview = null; text("library-import-result", msg("Import terminé : {0} création(s), {1} remplacement(s), {2} fiche(s) ignorée(s).", result.created, result.replaced, result.skipped));
    document.dispatchEvent(new CustomEvent("opt-station-library-changed"));
  }));
  document.addEventListener("opt-station-tab", event => { tab = event.detail.tab; if (tab === "configuration" && !dirty) refresh(); });
  document.addEventListener("opt-station-status", event => {
    const previousAccess = access; access = event.detail.access; browse = event.detail.browse ?? access; pendingPower = Boolean(event.detail.power?.pending);
    if (!access) { configuration = null; dirty = false; restorePreview = null; ["backup-password", "backup-password-confirm", "restore-password", "backup-auto-password"].forEach(id => { $(id).value = ""; }); if ($("backup-restore-dialog").open) $("backup-restore-dialog").close(); }
    if (!browse) { importPreview = null; ["library-import-dialog", "library-export-dialog"].forEach(id => { if ($(id).open) $(id).close(); }); $("library-export-items").replaceChildren(); $("library-import-items").replaceChildren(); }
    if (!previousAccess && access && tab === "configuration") refresh(); render();
  });
  document.addEventListener("opt-station-language", render);
  let poll = setInterval(async () => { if (tab === "configuration" && access && !busy && !dirty && document.visibilityState === "visible") { try { configuration = await request("/api/configuration/backups"); render(); } catch {} } }, 20000);
  window.addEventListener("pagehide", () => clearInterval(poll)); render();
})();
