"use strict";

// Les secrets et les adresses des appareils ne sont jamais utilisés comme sources
// d'images dans le navigateur : toutes les lectures passent par le Pi.
(() => {
  const I18n = window.OPT_I18N;
  I18n.init();
  const msg = I18n.msg;
  const $ = (id) => document.getElementById(id);
  let access = false, tab = "read", configuration = null, configurationLoading = false;
  let saving = false, polling = false, epoch = 0, dirty = false, latest = null;
  let cameraKey = "", thumbnailKey = "", largeCamera = null;
  const frames = new Map();
  const controllers = new Set();
  const value = (id) => $(id).value.trim();
  const set = (id, text) => { I18n.text($(id), text ?? "—"); };
  const number = (v, unit = "") => typeof v === "number" && Number.isFinite(v)
    ? `${new Intl.NumberFormat(I18n.locale(), {maximumFractionDigits: 1}).format(v)}${unit}` : "—";
  const clock = (stamp) => stamp ? new Date(stamp).toLocaleTimeString(I18n.locale(), {hour: "2-digit", minute: "2-digit", second: "2-digit"}) : "—";
  const duration = (seconds) => {
    if (typeof seconds !== "number") return "—";
    const minutes = Math.floor(seconds / 60);
    return minutes >= 60 ? `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, "0")}` : `${minutes} min`;
  };
  const stateNames = {IDLE: msg("Au repos"), BUSY: msg("Occupée"), READY: msg("Prête"), PRINTING: msg("Impression en cours"), PAUSED: msg("En pause"), FINISHED: msg("Terminée"), STOPPED: msg("Arrêtée"), ERROR: msg("Erreur"), ATTENTION: msg("Intervention requise")};
  function element(tag, className, content) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (content !== undefined) I18n.text(el, content);
    return el;
  }
  async function request(path, options = {}) {
    const controller = new AbortController();
    controllers.add(controller);
    const timeout = setTimeout(() => controller.abort(), 22000);
    try {
      const response = await fetch(path, {credentials: "same-origin", cache: "no-store", signal: controller.signal,
        ...options, ...(options.body ? {headers: {"Content-Type": "application/json"}, body: JSON.stringify(options.body)} : {})});
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(typeof detail.detail === "string" ? I18n.message(detail.detail) : msg("Lecture de l’appareil indisponible."));
      }
      return options.image ? await response.blob() : I18n.messages(await response.json());
    } catch (error) {
      if (error.name === "AbortError") throw new Error(msg("Lecture interrompue ou délai dépassé."));
      if (error instanceof TypeError) throw new Error(msg("La station est injoignable. Vérifiez la connexion au Pi."));
      throw error;
    } finally { clearTimeout(timeout); controllers.delete(controller); }
  }
  function sync() {
    $("printer-settings-fields").disabled = !access || !configuration || saving;
    ["printer-save", "printer-test", "printer-reload-settings"].forEach((id) => { $(id).disabled = !access || !configuration || saving; });
    $("printer-refresh").disabled = !access || polling;
    $("printer-add-camera").disabled = !access || saving || $("printer-camera-editors").children.length >= 4;
    $("printer-username-field").hidden = value("printer-auth") !== "digest";
    set("printer-settings-access", access ? msg("Les clés restent sur le Pi. Les champs secrets ne sont jamais renvoyés au navigateur.") : msg("Activez l’accès complet dans Paramètres → Accès distant pour configurer l’imprimante et ses caméras."));
  }
  function field(label, key, inputType = "text", initial = "") {
    const wrap = element("label", "field", label);
    const input = element("input");
    input.type = inputType; input.dataset.key = key; input.value = initial;
    input.autocomplete = inputType === "password" ? "new-password" : "off";
    input.maxLength = key === "url" ? 2000 : key === "secret" ? 1024 : 120;
    wrap.append(input);
    return wrap;
  }
  function cameraEditor(camera = {}) {
    const card = element("article", "printer-camera-editor");
    card.dataset.id = camera.id || "";
    const heading = element("div", "card-heading");
    const enabled = element("label", "printer-check");
    const check = element("input"); check.type = "checkbox"; check.dataset.key = "enabled"; check.checked = camera.enabled !== false;
    enabled.append(check, element("span", "", msg("Caméra active")));
    const remove = element("button", "button secondary", msg("Retirer")); remove.type = "button";
    remove.addEventListener("click", () => { card.remove(); markDirty(); sync(); });
    heading.append(enabled, remove);
    const grid = element("div", "form-grid");
    grid.append(field(msg("Nom de la vue"), "name", "text", camera.name || msg("Caméra")), field(msg("Adresse de la source"), "url", "text", camera.url || ""));
    grid.querySelector('[data-key="name"]').maxLength = 80;
    I18n.attribute(grid.querySelector('[data-key="url"]'), "placeholder", "rtsp://adresse-camera/live");
    const authLabel = element("label", "field", msg("Authentification"));
    const select = element("select"); select.dataset.key = "auth";
    [["none", msg("Sans identifiants")], ["basic", msg("Utilisateur et mot de passe")], ["digest", msg("Digest (image HTTP)")]].forEach(([v, label]) => {
      const option = element("option", "", label); option.value = v; select.append(option);
    });
    select.value = camera.auth || "none"; authLabel.append(select);
    const user = field(msg("Utilisateur"), "username", "text", camera.username || "");
    const secret = field(msg("Mot de passe"), "secret", "password");
    secret.append(element("span", "field-hint", camera.secret_saved ? msg("Secret enregistré; laisser vide pour le conserver.") : msg("Aucun secret enregistré.")));
    const clear = element("label", "printer-check");
    const clearInput = element("input"); clearInput.type = "checkbox"; clearInput.dataset.key = "clear_secret";
    clear.append(clearInput, element("span", "", msg("Effacer le secret enregistré")));
    grid.append(authLabel, user, secret, clear);
    const showAuth = () => { [user, secret, clear].forEach((el) => { el.hidden = select.value === "none"; }); };
    select.addEventListener("change", showAuth); showAuth();
    card.append(heading, grid); $("printer-camera-editors").append(card); sync();
  }
  function markDirty() {
    dirty = true;
    set("printer-settings-result", msg("Modifications à enregistrer."));
  }
  function fill(record) {
    configuration = record;
    const p = record.printer;
    $("printer-enabled").checked = p.enabled;
    $("printer-config-name").value = p.name;
    $("printer-url").value = p.url;
    $("printer-auth").value = p.auth;
    $("printer-username").value = p.username;
    $("printer-secret").value = ""; $("printer-clear-secret").checked = false;
    set("printer-secret-state", p.secret_saved ? msg("Secret enregistré; laisser vide pour le conserver.") : msg("Aucun secret enregistré."));
    $("printer-connect-uuid").value = record.connect.printer_uuid;
    $("printer-camera-editors").replaceChildren();
    record.cameras.forEach(cameraEditor);
    set("printer-ffmpeg-note", record.camera_capture_available ? msg("Capture RTSP disponible sur cette station. Actualisation des images toutes les 5 à 10 secondes selon la caméra, pendant la consultation.") : msg("La lecture RTSP nécessite FFmpeg sur le Pi. Les sources JPEG/PNG restent utilisables."));
    dirty = false; sync();
  }
  async function loadConfiguration() {
    if (!access || configurationLoading || saving) return;
    configurationLoading = true;
    set("printer-settings-result", msg("Chargement des réglages…"));
    const current = epoch;
    try {
      const record = await request("/api/configuration/printer");
      if (!access || current !== epoch) return;
      fill(record); set("printer-settings-result", msg("Réglages chargés depuis le Pi."));
    } catch (error) { if (access) set("printer-settings-result", error.message); }
    finally { configurationLoading = false; sync(); }
  }
  function settingsBody() {
    const cameras = [...$("printer-camera-editors").children].map((card) => {
      const get = (key) => card.querySelector(`[data-key="${key}"]`);
      return {id: card.dataset.id || null, enabled: get("enabled").checked,
        name: get("name").value.trim(), url: get("url").value.trim(), auth: get("auth").value,
        username: get("username").value.trim(), secret: get("secret").value || null, clear_secret: get("clear_secret").checked};
    });
    return {revision: configuration.revision,
      printer: {enabled: $("printer-enabled").checked, name: value("printer-config-name"), url: value("printer-url"),
        auth: value("printer-auth"), username: value("printer-username"), secret: $("printer-secret").value || null,
        clear_secret: $("printer-clear-secret").checked}, cameras, connect: {printer_uuid: value("printer-connect-uuid")}};
  }
  async function save(test = false) {
    if (!access || !configuration || saving) return;
    const current = epoch;
    saving = true; sync(); set("printer-settings-result", msg("Enregistrement des réglages…"));
    try {
      const body = settingsBody();
      const record = await request("/api/configuration/printer", {method: "PUT", body});
      if (!access || current !== epoch) return;
      fill(record); set("printer-settings-result", msg("Réglages enregistrés sur le Pi."));
      if (test) {
        set("printer-settings-result", msg("Lecture de la version, de l’état et du travail courant…"));
        const result = await request("/api/printer/status?refresh=true");
        if (!access || current !== epoch) return;
        latest = result;
        set("printer-settings-result", result.connected ? msg("Connexion PrusaLink vérifiée. Le suivi est en lecture seule.") : result.message);
      }
      cameraKey = ""; thumbnailKey = "";
    } catch (error) { if (access) set("printer-settings-result", error.message); }
    finally { saving = false; sync(); }
  }
  function clearViews() {
    controllers.forEach((c) => c.abort());
    frames.forEach((frame) => { if (frame.url) URL.revokeObjectURL(frame.url); }); frames.clear();
    $("printer-camera-grid").replaceChildren(); cameraKey = ""; thumbnailKey = "";
    $("printer-thumbnail").removeAttribute("src"); $("printer-thumbnail-wrap").hidden = true;
    if ($("printer-camera-dialog").open) $("printer-camera-dialog").close();
    $("printer-camera-large").removeAttribute("src"); largeCamera = null;
  }
  function render(snapshot) {
    set("printer-name", snapshot.name);
    set("printer-connection", snapshot.connected ? msg("Connectée") : snapshot.stale ? msg("Connexion perdue") : snapshot.configured ? msg("Injoignable") : msg("À configurer"));
    $("printer-connection").classList.toggle("in-stock", snapshot.connected);
    set("printer-message", snapshot.message);
    $("printer-message").className = snapshot.stale || snapshot.configured && !snapshot.connected ? "notice warning" : "notice";
    set("printer-updated", snapshot.observed_at ? `${snapshot.stale ? msg("Dernière mesure") : msg("Mesure reçue")} à ${clock(snapshot.observed_at)}` : "");
    const p = snapshot.printer || {}, job = snapshot.job || {}, info = snapshot.identity || {};
    set("printer-state", stateNames[p.state] || p.state || "—");
    set("printer-filename", job.filename || (job.id != null || ["PRINTING", "PAUSED"].includes(p.state) ? msg("Travail en cours · détails indisponibles") : snapshot.connected ? msg("Aucune impression en cours") : msg("Aucune impression connue")));
    set("printer-progress-value", number(job.progress, " %"));
    if (job.progress == null) $("printer-progress").removeAttribute("value");
    else $("printer-progress").value = job.progress;
    $("printer-progress").classList.toggle("unknown", job.progress == null);
    set("printer-elapsed", duration(job.time_printing)); set("printer-remaining", duration(job.time_remaining));
    const observed = snapshot.observed_at && Date.parse(snapshot.observed_at);
    set("printer-finish", typeof job.time_remaining === "number" && observed && !snapshot.stale ? clock(observed + job.time_remaining * 1000) : "—");
    set("printer-nozzle", `${number(p.temp_nozzle, " °C")} / ${number(p.target_nozzle, " °C")}`);
    set("printer-bed", `${number(p.temp_bed, " °C")} / ${number(p.target_bed, " °C")}`);
    set("printer-speed", number(p.speed, " %")); set("printer-z", number(p.axis_z, " mm"));
    set("printer-identity", [info.firmware ? `Firmware ${info.firmware}` : "", info.hostname || "", info.nozzle_diameter != null ? msg("Buse {0}", number(info.nozzle_diameter, " mm")) : ""].filter(Boolean).join(" · "));
    set("printer-consumption-message", snapshot.connect?.message);
    const key = JSON.stringify(snapshot.cameras || []);
    if (key !== cameraKey) {
      clearViews(); cameraKey = key;
      (snapshot.cameras || []).forEach((camera) => {
        const card = element("article", "printer-camera-card");
        const button = element("button", "printer-camera-open"); button.type = "button";
        I18n.attribute(button, "aria-label", msg("Agrandir {0}", camera.name));
        const img = element("img"); I18n.attribute(img, "alt", camera.name); img.hidden = true;
        const status = element("span", "printer-camera-placeholder", msg("Ouverture de la caméra…"));
        button.append(img, status);
        const note = element("p", "fine-print", msg("Image périodique"));
        button.addEventListener("click", () => {
          const frame = frames.get(camera.id);
          if (!frame?.url) return;
          largeCamera = camera.id; set("printer-camera-title", camera.name);
          $("printer-camera-large").src = frame.url; $("printer-camera-dialog").showModal();
        });
        card.append(element("h3", "", camera.name), button, note); $("printer-camera-grid").append(card);
        frames.set(camera.id, {img, status, note, pending: false, url: null});
      });
    }
    set("printer-camera-count", `${frames.size} / 4`); $("printer-cameras-empty").hidden = frames.size > 0;
    const preview = job.thumbnail_available && snapshot.connected ? `${job.id}:${job.filename}` : "";
    if (preview && preview !== thumbnailKey) {
      thumbnailKey = preview;
      $("printer-thumbnail").src = `/api/printer/thumbnail?v=${Date.now()}`;
      $("printer-thumbnail-wrap").hidden = false;
    } else if (!preview) { thumbnailKey = ""; $("printer-thumbnail").removeAttribute("src"); $("printer-thumbnail-wrap").hidden = true; }
  }
  async function refreshFrame(id, frame) {
    if (!access || tab !== "printer" || frame.pending) return;
    frame.pending = true;
    const current = epoch;
    try {
      const blob = await request(`/api/printer/cameras/${encodeURIComponent(id)}/image`, {image: true});
      if (!access || tab !== "printer" || current !== epoch || frames.get(id) !== frame) return;
      const old = frame.url; frame.url = URL.createObjectURL(blob);
      frame.img.src = frame.url; frame.img.hidden = false; frame.status.hidden = true;
      if (largeCamera === id) $("printer-camera-large").src = frame.url;
      if (old) URL.revokeObjectURL(old);
      I18n.text(frame.note, msg("Image reçue à {0}", clock(Date.now())));
    } catch (error) {
      if (access && frames.get(id) === frame) {
        I18n.text(frame.status, msg("Caméra indisponible")); frame.status.hidden = false;
        I18n.text(frame.note, frame.url ? msg("Dernière image conservée · connexion à vérifier") : error.message);
      }
    } finally { frame.pending = false; }
  }
  async function refresh(force = false) {
    if (!access || tab !== "printer" || polling || document.visibilityState !== "visible") return;
    polling = true; sync(); const current = epoch;
    try {
      const snapshot = await request(`/api/printer/status${force ? "?refresh=true" : ""}`);
      if (!access || tab !== "printer" || current !== epoch) return;
      latest = snapshot; render(snapshot);
      frames.forEach((frame, id) => { void refreshFrame(id, frame); });
    } catch (error) {
      if (access && tab === "printer") {
        if (latest) render({...latest, connected: false, stale: true, message: error.message});
        set("printer-message", error.message); set("printer-connection", msg("Station injoignable"));
        $("printer-connection").classList.remove("in-stock"); $("printer-message").className = "notice warning";
        frames.forEach((frame) => { if (frame.url) I18n.text(frame.note, msg("Dernière image conservée · station injoignable")); });
      }
    }
    finally { polling = false; sync(); }
  }
  document.addEventListener("opt-station-status", (event) => {
    const next = Boolean(event.detail.access);
    if (access && !next) {
      epoch++; clearViews(); configuration = null; latest = null; dirty = false;
      ["printer-url", "printer-secret", "printer-username", "printer-connect-uuid"].forEach((id) => { $(id).value = ""; });
      $("printer-camera-editors").replaceChildren(); set("printer-settings-result", "");
      render({name: msg("Imprimante"), connected: false, configured: false, cameras: [], message: msg("Activez l’accès complet dans Paramètres → Accès distant pour consulter le suivi.")});
    }
    const gained = next && !access; access = next; sync();
    if (access && (gained || !configuration) && tab === "configuration") void loadConfiguration();
    if (gained && tab === "printer") void refresh();
  });
  document.addEventListener("opt-station-tab", (event) => {
    if (tab !== event.detail.tab) { epoch++; clearViews(); }
    tab = event.detail.tab;
    if (tab === "configuration" && access && !configuration && !dirty) void loadConfiguration();
    if (tab === "printer") { if (latest) render(latest); void refresh(); }
  });
  $("printer-settings-form").addEventListener("input", () => { markDirty(); sync(); });
  $("printer-settings-form").addEventListener("change", () => { markDirty(); sync(); });
  $("printer-settings-form").addEventListener("submit", (event) => { event.preventDefault(); void save(); });
  $("printer-test").addEventListener("click", () => void save(true));
  $("printer-reload-settings").addEventListener("click", () => {
    if (!dirty || confirm(msg("Recharger les réglages du Pi et abandonner les modifications non enregistrées ?"))) void loadConfiguration();
  });
  $("printer-add-camera").addEventListener("click", () => { if ($("printer-camera-editors").children.length < 4) { cameraEditor(); markDirty(); } });
  $("printer-refresh").addEventListener("click", () => void refresh(true));
  $("printer-thumbnail").addEventListener("error", () => { $("printer-thumbnail-wrap").hidden = true; });
  $("printer-camera-dialog").addEventListener("close", () => { largeCamera = null; $("printer-camera-large").removeAttribute("src"); });
  document.addEventListener("opt-printer-refresh", () => void refresh(true));
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") void refresh(); });
  const timer = setInterval(() => void refresh(), 5000);
  document.addEventListener("opt-station-language", () => { sync(); if (latest) render(latest); });
  window.addEventListener("pagehide", () => { clearInterval(timer); epoch++; clearViews(); });
  sync();
})();
