"use strict";

(() => {
  const I18n = window.OPT_I18N;
  I18n.init();
  const msg = I18n.msg;
  const $ = (id) => document.getElementById(id);
  const state = {
    status: null, schema: {main: [], aux: []}, currentTag: null,
    editorTag: null, editorMode: "create", preview: null,
    inventory: [], inventoryView: "stock", favorites: [], editingFavorite: null, deletingFavorite: null, lastRead: null,
    activeTab: "read", toastTimer: null, sourceQR: null, sourceFavorite: null,
    cameraScan: null, cameraEpoch: 0, cameraTimer: null, cameraStarting: false,
    cameraFrame: null, cameraResults: null, qrEpoch: 0,
    previousStationAccess: null,
    configuration: null, configurationPending: false, networkSettingsDirty: false,
    previousRemoteAccess: null,
    qrData: null, stockSource: null, cameraTarget: "editor",
    packagedUUID: null, packagedSource: null, packagedQR: null, packagedEpoch: 0, packagedAnalyzing: false,
    modelSourceEpoch: 0, modelSourceBusy: false,
    labelPreview: null, labelRequestId: null, labelsSettings: null, labelsDirty: false, labelsLoading: false,
    inventoryNotes: null, inventoryNotesDirty: false, inventoryNotesBusy: false,
    spoolNotesDrafts: new Map(),
  };
  const coreMain = new Set([
    "material_class", "material_type", "brand_name", "material_name", "gtin",
    "nominal_netto_full_weight", "actual_netto_full_weight", "empty_container_weight",
    "primary_color", "filament_diameter", "min_print_temperature", "max_print_temperature",
    "min_bed_temperature", "max_bed_temperature",
  ]);
  const coreAux = new Set(["consumed_weight", "storage_location"]);
  const individualFields = new Set([
    "instance_uuid", "brand_specific_instance_id", "actual_netto_full_weight",
    "actual_full_length", "manufactured_date", "expiration_date", "write_protection",
  ]);
  const labels = {
    material_class: msg("Famille de matériau"), material_type: msg("Type de matériau"),
    material_name: msg("Nom du matériau"), material_abbreviation: msg("Abréviation"),
    brand_name: msg("Marque"), gtin: msg("Code produit GTIN"), instance_uuid: msg("Identité de la bobine"),
    package_uuid: msg("Identité du produit"), material_uuid: msg("Identité du matériau"), brand_uuid: msg("Identité de la marque"),
    brand_specific_instance_id: msg("Identifiant de bobine du fabricant"), brand_specific_package_id: msg("Référence produit du fabricant"),
    brand_specific_material_id: msg("Référence matériau du fabricant"), write_protection: msg("Protection déclarée"),
    manufactured_date: msg("Date de fabrication"), expiration_date: msg("Date d’expiration"), country_of_origin: msg("Pays d’origine"),
    nominal_netto_full_weight: msg("Poids net initial nominal"), actual_netto_full_weight: msg("Poids net initial réel"),
    empty_container_weight: msg("Poids du contenant vide"), nominal_full_length: msg("Longueur initiale nominale"),
    actual_full_length: msg("Longueur initiale réelle"), primary_color: msg("Couleur principale"),
    primary_color_lab: msg("Couleur principale CIELAB"), primary_color_ral: msg("Couleur principale RAL"),
    secondary_color_0: msg("Couleur secondaire 1"), secondary_color_1: msg("Couleur secondaire 2"),
    secondary_color_2: msg("Couleur secondaire 3"), secondary_color_3: msg("Couleur secondaire 4"),
    secondary_color_4: msg("Couleur secondaire 5"), density: msg("Densité"), filament_diameter: msg("Diamètre du filament"),
    min_print_temperature: msg("Température de buse minimale"), max_print_temperature: msg("Température de buse maximale"),
    min_bed_temperature: msg("Température de plateau minimale"), max_bed_temperature: msg("Température de plateau maximale"),
    min_chamber_temperature: msg("Température d’enceinte minimale"), max_chamber_temperature: msg("Température d’enceinte maximale"),
    chamber_temperature: msg("Température d’enceinte"), preheat_temperature: msg("Température de préchauffage"),
    min_nozzle_diameter: msg("Diamètre minimal de buse"), container_width: msg("Largeur de la bobine"),
    container_outer_diameter: msg("Diamètre extérieur de la bobine"), container_inner_diameter: msg("Diamètre intérieur de la bobine"),
    container_hole_diameter: msg("Diamètre du trou de la bobine"), consumed_weight: msg("Matière déjà consommée"),
    storage_location: msg("Emplacement de stockage"), workgroup: msg("Groupe de travail"),
    general_purpose_range_user: msg("Identifiant des champs personnalisés"), last_stir_time: msg("Dernier mélange de résine"),
    purchase_time: msg("Date d’achat"), purchase_price: msg("Prix d’achat"), purchase_currency: msg("Devise d’achat"),
    certifications: "Certifications", tags: msg("Caractéristiques matière"), transmission_distance: msg("Transmission lumineuse"),
    hardness_shore_a: msg("Dureté Shore A"), hardness_shore_d: msg("Dureté Shore D"),
  };
  const nameOf = (name) => labels[name] || String(name).replaceAll("_", " ");
  const clone = (value) => value == null ? value : JSON.parse(JSON.stringify(value));
  let numberFormat = new Intl.NumberFormat(I18n.locale(), {maximumFractionDigits: 2});
  const grams = (value) => typeof value === "number" && Number.isFinite(value) ? `${numberFormat.format(value)} g` : msg("Inconnu");
  const formatDate = (value) => {
    if (!value) return msg("Aucune lecture");
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? msg("Date non disponible") : date.toLocaleString(I18n.locale(), {dateStyle: "short", timeStyle: "short"});
  };
  const fieldDef = (region, name) => (state.schema[region] || []).find((field) => field.name === name);
  const canControl = () => Boolean(state.status?.station_access ?? state.status?.local_station);
  const canBrowse = () => Boolean(state.status?.local_station) || state.status?.network?.mode !== "disabled";
  const isSimulation = () => state.status?.mode === "simulation";
  const isBlank = (tag) => Boolean(tag) && !Object.keys(tag.main || {}).length && !Object.keys(tag.aux || {}).length;
  const initialWeight = (tag) => tag?.main?.actual_netto_full_weight ?? tag?.main?.nominal_netto_full_weight;

  const newUUID = () => {
    const bytes = crypto.getRandomValues(new Uint8Array(16)); bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
    const hex = [...bytes].map((x) => x.toString(16).padStart(2, "0")).join("");
    return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
  };
  const stockDate = (item) => item.added_at ? new Date(item.added_at).toLocaleDateString(I18n.locale()) : msg("Date inconnue");
  const stockAge = (item) => item.age_days == null ? msg("Ancienneté inconnue") : item.age_days === 0 ? msg("Entrée aujourd’hui") : msg("Depuis {0} jour{1}", item.age_days, item.age_days > 1 ? "s" : "");
  const identification = (item) => item.label_state === "qr" ? "▦ QR" : "◎ RFID";
  const usageState = (item) => item.completed_at ? msg("✓ Terminée · archivée") : item.usage_state === "stock" ? msg("En stock") : msg("En service");

  function node(tag, className, text) {
    const result = document.createElement(tag);
    if (className) result.className = className;
    if (text !== undefined && text !== null) I18n.text(result, text);
    return result;
  }
  function setText(id, text) { I18n.text($(id), text ?? ""); }
  function clear(element) { element.replaceChildren(); }
  function notify(message, error = false) {
    clearTimeout(state.toastTimer);
    const toast = $("toast");
    I18n.text(toast, I18n.message(message));
    toast.classList.toggle("error", error);
    toast.setAttribute("role", error ? "alert" : "status");
    toast.hidden = false;
    state.toastTimer = setTimeout(() => { toast.hidden = true; }, error ? 11000 : 6500);
  }
  function detailMessage(detail) {
    if (typeof detail === "string") return I18n.message(detail);
    if (Array.isArray(detail)) return detail.map((entry) => entry.msg || JSON.stringify(entry)).join(" · ");
    if (detail && typeof detail === "object") return detail.message || JSON.stringify(detail);
    return msg("L’opération n’a pas pu être terminée.");
  }
  async function api(path, options = {}) {
    if (state.status?.power?.pending && ((options.method || "GET") !== "GET" || path === "/api/reader/tag")) {
      throw new Error(msg("Le Pi s’arrête ou redémarre. Attendez son retour avant de lancer une opération."));
    }
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), path === "/api/reader/write" || path.endsWith("/print") ? 60000 : 30000);
    try {
      const response = await fetch(path, {
        method: options.method || "GET", credentials: "same-origin", cache: "no-store",
        headers: options.body !== undefined ? {"Content-Type": "application/json"} : {},
        ...(options.body !== undefined ? {body: JSON.stringify(options.body)} : {}),
        signal: controller.signal,
      });
      const text = await response.text();
      let result;
      try { result = text ? JSON.parse(text) : {}; }
      catch { throw new Error(msg("Réponse de la station illisible. Actualisez la page.")); }
      if (!response.ok) {
        const error = new Error(detailMessage(result.detail ?? result.message));
        error.status = response.status;
        throw error;
      }
      return I18n.messages(result);
    } catch (error) {
      if (error.name === "AbortError") throw new Error(msg("La station n’a pas répondu. Vérifiez son état avant de renouveler une opération."));
      if (error instanceof TypeError) throw new Error(msg("La station est injoignable. Vérifiez la connexion puis actualisez."));
      throw error;
    } finally { clearTimeout(timeout); }
  }
  const post = (path, body = {}) => api(path, {method: "POST", body});
  async function task(button, operation) {
    const wasDisabled = button?.disabled;
    if (button) { button.disabled = true; button.dataset.pending = "true"; button.classList.add("loading"); }
    try { return await operation(); }
    catch (error) { notify(error.message || msg("Une erreur est survenue."), true); }
    finally {
      if (button) { delete button.dataset.pending; button.classList.remove("loading"); button.disabled = wasDisabled; }
      syncControls();
    }
  }
  function disabled(id, value) { if (!$(id).dataset.pending) $(id).disabled = value; }
  function syncControls() {
    const readerReady = canControl() && Boolean(state.status?.reader?.connected);
    ["read-tag", "load-current"].forEach((id) => disabled(id, !readerReady));
    ["sim-select", "sim-blank", "sim-consume"].forEach((id) => disabled(id, !canControl() || !isSimulation()));
    const associationPending = Boolean(state.currentTag?.association_pending);
    disabled("inventory-toggle", !readerReady || !state.currentTag || isBlank(state.currentTag) || associationPending || Boolean(state.currentTag?.inventory?.completed_at));
    disabled("edit-current", !readerReady || !state.currentTag || isBlank(state.currentTag) || associationPending);
    disabled("confirm-tag-association", !readerReady || !associationPending);
    disabled("model-from-tag", !readerReady || !state.currentTag || isBlank(state.currentTag));
    disabled("library-source-open", !state.status || !state.schema.main.length || !canBrowse());
    $("model-source-access").hidden = canControl();
    disabled("model-source-rfid", !readerReady || state.modelSourceBusy);
    disabled("model-source-inspect", !canBrowse() || state.modelSourceBusy);
    disabled("model-source-camera", !canControl() || !state.status?.camera?.available || state.modelSourceBusy);
    disabled("save-favorite", !canBrowse() || Boolean(state.status?.power?.pending));
    disabled("prepare-write", !readerReady || !state.editorTag || Boolean(state.editorTag?.association_pending) || Boolean(state.stockSource?.completed_at) || (state.editorMode === "create" ? !isBlank(state.editorTag) : isBlank(state.editorTag)));
    disabled("confirm-write", !readerReady || !state.preview);
    disabled("apply-favorite", !$("favorite-select").value || state.editorMode !== "create");
    disabled("inspect-qr", !canControl() || state.editorMode !== "create");
    disabled("camera-open", !canControl() || state.editorMode !== "create" || !state.status?.camera?.available);
    disabled("camera-stop", state.cameraStarting || !state.cameraScan?.active || state.cameraScan?.state === "stopping");
    disabled("camera-retry", state.cameraStarting || Boolean(state.cameraScan?.active));
    disabled("save-network-settings", !state.status?.network?.configured || !state.networkSettingsDirty);
    disabled("new-packaged", !state.status || !canBrowse());
    disabled("packaged-save", !canBrowse() || state.packagedAnalyzing);
    disabled("packaged-inspect", !canBrowse() || state.packagedAnalyzing);
    const draft = state.detailItem && state.spoolNotesDrafts.get(state.detailItem.id);
    $("inventory-notes").disabled = !canBrowse() || !state.inventoryNotes || state.inventoryNotesBusy || Boolean(state.status?.power?.pending);
    disabled("inventory-notes-save", !canBrowse() || !state.inventoryNotes || !state.inventoryNotesDirty || state.inventoryNotesBusy || Boolean(state.status?.power?.pending));
    disabled("inventory-notes-reload", !canBrowse() || state.inventoryNotesBusy);
    $("spool-notes").disabled = !canBrowse() || !draft || draft.busy || Boolean(state.status?.power?.pending);
    disabled("spool-notes-save", !canBrowse() || !draft?.dirty || draft?.busy || Boolean(state.status?.power?.pending));
    disabled("spool-notes-reload", !canBrowse() || !draft || draft.busy);
    disabled("confirm-delete-favorite", !canBrowse() || !state.deletingFavorite || Boolean(state.status?.power?.pending));
    disabled("packaged-camera", !canControl() || !state.status?.camera?.available || state.packagedAnalyzing);
    disabled("label-print", !canControl() || !state.labelPreview?.print_enabled);
    disabled("label-prepare", !canControl() || state.labelPreview?.item?.label_state !== "qr" || !state.labelPreview?.item?.in_stock);
    disabled("label-associate", !canControl() || state.labelPreview?.item?.label_state !== "qr" || !state.labelPreview?.item?.in_stock);
    $("labels-settings-fields").disabled = !canControl() || state.labelsLoading || !state.labelsSettings;
    disabled("labels-save", !canControl() || !state.labelsSettings || !state.labelsDirty);
    disabled("labels-probe", !canControl() || !state.labelsSettings);
    disabled("labels-reload", !canControl());
  }
  function invalidatePreview() {
    state.preview = null;
    $("write-preview").hidden = true;
    syncControls();
  }
  function showTab(tab, focus = false) {
    if (!canControl() && state.status && !["inventory", "configuration"].includes(tab)) return;
    if (!canBrowse() && tab !== "configuration") return;
    if (tab !== "write" && $("camera-dialog").open) $("camera-dialog").close();
    state.activeTab = tab;
    document.body.dataset.tab = tab;
    document.querySelectorAll(".tab").forEach((button) => {
      const active = button.dataset.tab === tab;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", String(active));
      button.tabIndex = active ? 0 : -1;
      if (active && focus) button.focus();
    });
    document.querySelectorAll(".tab-panel").forEach((panel) => { panel.hidden = panel.id !== `panel-${tab}`; });
    setText("page-breadcrumb", {read: msg("LECTURE"), write: msg("ÉCRITURE"), inventory: msg("INVENTAIRE"), printer: msg("IMPRIMANTE"), configuration: msg("CONFIGURATION")}[tab]);
    document.dispatchEvent(new CustomEvent("opt-station-tab", {detail: {tab}}));
    if (tab === "inventory") task(null, () => Promise.all([refreshStock(), refreshFavorites(), refreshInventoryNotes()]));
    if (tab === "configuration") task(null, refreshConfiguration);
  }

  function renderStatus() {
    const status = state.status;
    if (state.previousStationAccess === true && !canControl()) {
      if ($("camera-dialog").open) $("camera-dialog").close();
      state.currentTag = null;
      setEditorMode("create", null);
      notify(canBrowse() ? msg("Accès complet fermé. L’inventaire et les favoris restent disponibles.") : msg("Les accès distants ont été désactivés sur le Pi."));
    }
    state.previousStationAccess = canControl();
    if (!canBrowse()) {
      state.currentTag = null; state.inventory = []; state.favorites = [];
      state.inventoryNotes = null; state.inventoryNotesDirty = false; state.spoolNotesDrafts.clear();
      $("inventory-notes").value = ""; $("spool-notes").value = "";
      clear($("inventory-list")); clear($("favorites-list"));
      ["detail-dialog", "favorite-dialog", "delete-favorite-dialog", "packaged-dialog", "label-dialog", "model-source-dialog"].forEach((id) => { if ($(id).open) $(id).close(); });
    }
    const simulated = isSimulation();
    const connected = Boolean(status.reader?.connected);
    const present = Boolean(status.reader?.present);
    setText("reader-status", simulated ? msg("Lecteur simulé") : connected ? (present ? msg("Tag présent") : msg("Lecteur connecté")) : msg("Lecteur non raccordé"));
    ["reader-dot", "sidebar-dot"].forEach((id) => { $(id).classList.toggle("online", connected); $(id).classList.toggle("offline", !connected); });
    setText("station-label", status.local_station ? msg("Station locale") : !canBrowse() ? msg("Réseau · désactivé") : canControl() ? msg("Réseau · accès complet") : msg("Réseau · inventaire"));
    setText("app-version", status.version ? `Version ${status.version}` : "");
    $("simulator-panel").hidden = !simulated || !canControl();
    ["read", "write", "printer"].forEach((tab) => {
      const button = $(`tab-${tab}`);
      button.disabled = !canControl();
      I18n.attribute(button, "title", canControl() ? "" : msg("Activez l’accès complet dans Configuration → Accès distant"));
    });
    $("tab-inventory").disabled = !canBrowse();
    if (!canBrowse() && state.activeTab !== "configuration") showTab("configuration");
    else if (!canControl() && !["inventory", "configuration"].includes(state.activeTab)) showTab("inventory");
    I18n.text($("read-empty").querySelector("p"), simulated ? msg("Choisissez un tag simulé, puis lancez une lecture.") : msg("Posez un tag NFC-V au centre du lecteur, puis lancez une lecture."));
    setText("confirm-write", simulated ? msg("Simuler l’écriture") : msg("Écrire et vérifier le tag"));
    setText("camera-availability", !canControl() ? msg("Activez l’accès complet dans Configuration → Accès distant pour utiliser la caméra du Pi.") : status.camera?.available ? msg("Scannez avec la caméra du Pi, ou saisissez le texte d’un code. Vous vérifierez son contenu avant de l’utiliser.") : msg("{0} La saisie du texte reste disponible.", status.camera?.message || msg("Caméra indisponible.")));
    renderConfiguration();
    syncControls();
    document.dispatchEvent(new CustomEvent("opt-station-status", {detail: {access: canControl(), browse: canBrowse(), power: status.power, mcp: status.mcp, updates: status.updates}}));
  }

  function renderConfiguration() {
    if (!state.status) return;
    const network = state.status.network || {};
    const editable = Boolean(network.configured);
    disabled("refresh-configuration", false);
    const reader = state.status.reader || {}, camera = {...state.status.camera, ...state.configuration?.camera};
    const multipleReaders = (reader.detected_readers?.length || 0) > 1;
    setText("configuration-mode-badge", isSimulation() ? "Simulation" : msg("Matériel réel"));
    setText("configuration-mode-note", isSimulation() ? msg("Les tags et les écritures NFC sont simulés.") : msg("Le lecteur et la caméra affichés sont ceux raccordés au Pi."));
    setText("configuration-reader-name", reader.simulated ? msg("Lecteur simulé") : reader.connected ? reader.name || msg("Lecteur NFC") : multipleReaders ? msg("Plusieurs lecteurs détectés") : msg("Aucun lecteur compatible détecté"));
    setText("configuration-reader-detail", reader.simulated ? msg("Démonstration, sans lecteur physique.") : reader.message || msg("Branchez un lecteur compatible sur le Pi."));
    $("configuration-reader-technical").hidden = !reader.pcsc_name;
    setText("configuration-reader-id", reader.pcsc_name || "");
    setText("configuration-reader-state", reader.simulated ? "Simulation" : reader.connected ? msg("Connecté") : multipleReaders ? msg("À vérifier") : msg("Absent"));
    $("configuration-reader-state").classList.toggle("in-stock", Boolean(reader.connected) && !reader.simulated);
    setText("configuration-camera-name", camera.model ? String(camera.model).toUpperCase() : state.configurationPending ? msg("Identification du capteur…") : camera.detected === false ? msg("Aucune caméra détectée") : camera.detection_message ? msg("Détection indisponible") : msg("Détection à actualiser"));
    setText("configuration-camera-state", camera.detected ? msg("Détectée") : camera.detected === false ? msg("Absente") : msg("À vérifier"));
    $("configuration-camera-state").classList.toggle("in-stock", Boolean(camera.detected));
    setText("configuration-camera-detail", [camera.detection_message, camera.enabled === false ? msg("Capture QR désactivée.") : camera.available === false ? camera.message : null].filter(Boolean).join(" "));
    setText("configuration-network-state", !network.configured ? msg("Non activé") : {disabled: msg("Désactivé"), inventory: msg("Inventaire"), full: msg("Complet sans code")}[network.mode] || msg("Inventaire"));
    $("network-settings-fields").disabled = !editable;
    disabled("save-network-settings", !editable || !state.networkSettingsDirty);
    setText("configuration-network-help", !network.configured ? msg("L’écoute réseau doit être activée avec --lan sur la station.") : network.mode === "full" ? msg("Accès complet ouvert aux machines du réseau local, sans code et sans expiration. Le choix est conservé après redémarrage, jusqu’à ce que vous le changiez ici.") : network.mode === "inventory" ? msg("Le stock et les modèles restent accessibles. Pour utiliser aussi le lecteur NFC, les caméras et le suivi imprimante depuis le bureau, choisissez Accès complet sans code.") : msg("Les fonctions distantes sont désactivées. Configuration reste accessible pour les réactiver depuis cet ordinateur. Le choix est conservé après redémarrage."));
    if (!state.networkSettingsDirty) {
      document.querySelectorAll('input[name="remote-mode"]').forEach((input) => { input.checked = input.value === (network.mode || "inventory"); });
    }
    $("configuration-network-link").hidden = !network.url;
    setText("configuration-network-address", network.url || "");
    $("configuration-network-address").href = network.url || "#";
  }

  async function refreshConfiguration(refresh = false) {
    if (state.configurationPending || !state.status) return;
    state.configurationPending = true;
    setText("configuration-hardware-message", msg("Détection du matériel…"));
    renderConfiguration();
    try {
      state.configuration = await api(`/api/configuration${refresh ? "?refresh=true" : ""}`);
      setText("configuration-hardware-message", msg("Matériel actualisé. La détection du capteur ne démarre pas de capture."));
    } catch (error) {
      setText("configuration-hardware-message", error.message);
    } finally { state.configurationPending = false; renderConfiguration(); }
  }

  document.querySelectorAll('input[name="remote-mode"]').forEach((input) => input.addEventListener("change", () => {
    state.networkSettingsDirty = true;
    setText("configuration-network-result", msg("Modification à enregistrer."));
    renderConfiguration();
  }));
  $("refresh-configuration").addEventListener("click", (event) => task(event.currentTarget, () => refreshConfiguration(true)));
  $("network-settings-form").addEventListener("submit", (event) => {
    event.preventDefault();
    task($("save-network-settings"), async () => {
      const mode = document.querySelector('input[name="remote-mode"]:checked')?.value;
      if (!mode || !state.status.network?.configured) return;
      const couldBrowse = canBrowse(), couldControl = canControl();
      await api("/api/configuration/network", {method: "PUT", body: {mode}});
      state.status = await api("/api/status");
      state.networkSettingsDirty = false;
      renderStatus();
      if (!couldBrowse && canBrowse()) {
        state.schema = await api("/api/schema");
        setEditorMode("create");
        await Promise.all([refreshStock(), refreshFavorites(), refreshSimulator(), refreshInventoryNotes()]);
      } else if (!couldControl && canControl()) await refreshSimulator();
      state.previousRemoteAccess = canBrowse();
      setText("configuration-network-result", msg("Choix enregistré sur le Pi, sans expiration et conservé après redémarrage."));
      notify(msg("Le partage a été mis à jour pour les machines du réseau local."));
    });
  });

  function displayValue(region, name, value) {
    if (value === null || value === undefined || value === "") return msg("Non renseigné");
    const def = fieldDef(region, name);
    if (def?.options?.length) {
      if (Array.isArray(value)) return value.map((item) => def.options.find((option) => String(option.value) === String(item))?.label ?? String(item)).join(", ");
      const option = def.options.find((item) => String(item.value) === String(value));
      if (option) return String(option.label);
    }
    if (typeof value === "object") return JSON.stringify(value);
    if (typeof value === "number") return `${numberFormat.format(value)}${def?.unit ? ` ${def.unit}` : ""}`;
    return String(value);
  }
  function colour(element, value) {
    if (typeof value === "string" && /^#[0-9a-f]{6}([0-9a-f]{2})?$/i.test(value)) element.style.setProperty("--spool-color", value.slice(0, 7));
    else element.style.setProperty("--spool-color", "#82948a");
  }
  function swatch(value) {
    const element = node("span", "swatch");
    if (typeof value === "string" && /^#[0-9a-f]{6}([0-9a-f]{2})?$/i.test(value)) element.style.backgroundColor = value;
    element.setAttribute("aria-hidden", "true");
    return element;
  }
  function spoolName(entry) { return entry.main?.material_name || entry.main?.brand_specific_package_id || (isBlank(entry) ? msg("Tag vierge") : msg("Bobine sans nom")); }
  function spoolTitle(entry) {
    const number = entry.spool_number || entry.inventory?.spool_number;
    return number ? `${number} · ${spoolName(entry)}` : spoolName(entry);
  }
  function renderFieldTables(container, tag) {
    clear(container);
    for (const [region, title] of [["main", msg("Matériau et bobine")], ["aux", msg("Suivi et informations personnelles")]]) {
      const fields = tag[region] || {};
      container.append(node("h3", "", title));
      if (!Object.keys(fields).length) { container.append(node("p", "muted", msg("Aucune donnée renseignée."))); continue; }
      const table = node("table", "data-table");
      const tbody = node("tbody");
      for (const [name, value] of Object.entries(fields)) {
        const row = node("tr");
        row.append(node("td", "", nameOf(name)), node("td", "", displayValue(region, name, value)));
        tbody.append(row);
      }
      table.append(tbody); container.append(table);
    }
  }
  function renderReader() {
    const tag = state.currentTag;
    $("read-empty").hidden = Boolean(tag);
    $("read-result").hidden = !tag;
    if (!tag) return;
    setText("spool-brand", tag.main?.brand_name || msg("Marque non renseignée"));
    setText("spool-name", spoolTitle(tag));
    const pills = $("spool-material"); clear(pills);
    for (const name of ["material_class", "material_type"]) if (tag.main?.[name] !== undefined) pills.append(node("span", "", displayValue("main", name, tag.main[name])));
    if (tag.main?.primary_color) pills.append(node("span", "", tag.main.primary_color));
    colour($("spool-visual"), tag.main?.primary_color);
    const inStock = Boolean(tag.inventory?.in_stock);
    const completed = Boolean(tag.inventory?.completed_at);
    const pending = tag.association_pending;
    $("reader-association-note").hidden = !pending;
    $("confirm-tag-association").hidden = !pending;
    if (pending) setText("reader-association-note", msg("Le tag de la bobine {0} est écrit. Confirmez son association pour remplacer l’ancien tag, sans nouvelle écriture.", pending.spool_number));
    setText("spool-stock", pending ? msg("Association à confirmer") : completed ? msg("Terminée · archivée") : inStock ? usageState(tag.inventory) : msg("Hors inventaire"));
    $("spool-stock").classList.toggle("in-stock", inStock);
    setText("inventory-toggle", completed ? msg("Bobine terminée") : inStock ? msg("Retirer de l’inventaire") : msg("Ajouter à l’inventaire"));
    $("inventory-toggle").classList.toggle("danger", inStock);
    $("inventory-toggle").classList.toggle("primary", !inStock);
    setText("remaining-value", grams(tag.remaining_weight));
    setText("remaining-note", tag.remaining_weight == null ? msg("Poids initial ou consommation non renseigné.") : tag.remaining_estimated ? msg("Estimation à partir du poids initial nominal.") : msg("Calcul à partir du poids initial réel et du consommé."));
    const initial = initialWeight(tag);
    const ratio = typeof initial === "number" && initial > 0 && typeof tag.remaining_weight === "number" ? Math.min(100, Math.max(0, tag.remaining_weight / initial * 100)) : 0;
    $("remaining-bar").style.width = `${ratio}%`;
    setText("initial-weight", grams(initial));
    setText("consumed-weight", grams(tag.aux?.consumed_weight));
    setText("filament-diameter", tag.main?.filament_diameter == null ? msg("Non renseigné") : `${numberFormat.format(tag.main.filament_diameter)} mm`);
    setText("tag-uid", tag.uid || msg("Inconnu"));
    setText("main-protection", tag.protections?.main ? msg("Protégées · lecture seule") : msg("Modifiables"));
    setText("aux-protection", tag.protections?.aux ? msg("Protégées · lecture seule") : msg("Modifiables"));
    setText("read-time", formatDate(state.lastRead));
    const usage = $("memory-info"); clear(usage);
    if (tag.usage) {
      if (tag.usage.main_capacity != null) usage.append(node("p", "", msg("Matériau : {0} / {1} octets", tag.usage.main_used ?? "—", tag.usage.main_capacity)));
      if (tag.usage.aux_capacity != null) usage.append(node("p", "", msg("Suivi : {0} / {1} octets", tag.usage.aux_used ?? "—", tag.usage.aux_capacity)));
    }
    renderFieldTables($("read-fields"), tag);
    syncControls();
  }
  function setCurrentTag(tag) {
    state.currentTag = tag;
    state.lastRead = new Date().toISOString();
    if (state.editorMode === "create") state.editorTag = clone(tag);
    invalidatePreview();
    renderReader(); renderEditorNote();
  }
  async function scan() {
    const tag = await api("/api/reader/tag");
    setCurrentTag(tag);
    await refreshStock();
    return tag;
  }
  async function refreshSimulator() {
    if (!isSimulation() || !canControl()) return;
    const response = await api("/api/simulator/tags");
    const select = $("sim-tag"); clear(select);
    for (const tag of response.items || []) {
      const option = node("option", "", tag.label || `${tag.blank ? msg("Tag vierge") : msg("Tag simulé")} · ${tag.uid}`);
      option.value = tag.uid;
      select.append(option);
    }
    if (state.currentTag?.uid) select.value = state.currentTag.uid;
  }

  function rawValue(field, value) {
    if (value == null) return "";
    if (Array.isArray(value) || (typeof value === "object")) return JSON.stringify(value);
    return String(value);
  }
  function buildField(field, region, value, prefix, protectedRegion = false) {
    const label = node("label", `field${["enum_array", "color_lab"].includes(field.type) ? " wide" : ""}`);
    const title = node("span", "field-title", nameOf(field.name));
    if (field.required === true || field.required === "required") title.append(node("span", "required-star", "*"));
    if (field.unit) title.append(node("span", "field-unit", field.unit));
    if (protectedRegion) title.append(node("span", "protected-label", msg("Protégé")));
    label.append(title);
    let input;
    if (field.type === "enum" && field.options?.length) {
      input = node("select");
      const blank = node("option", "", msg("Choisir…")); blank.value = ""; input.append(blank);
      for (const option of field.options) { const item = node("option", "", option.label ?? option.value); item.value = String(option.value); input.append(item); }
      if (value != null && !field.options.some((option) => String(option.value) === String(value))) {
        const unknown = node("option", "", msg("Valeur inconnue : {0}", value)); unknown.value = String(value); input.append(unknown);
      }
    } else if (["enum_array", "color_lab"].includes(field.type)) input = node("textarea");
    else {
      input = node("input");
      input.type = ["number", "int", "timestamp"].includes(field.type) ? "number" : "text";
      if (input.type === "number") input.step = ["int", "timestamp"].includes(field.type) ? "1" : "any";
      if (field.type === "color_rgba") I18n.attribute(input, "placeholder", "#RRGGBB ou #RRGGBBAA");
      else if (field.type === "uuid") I18n.attribute(input, "placeholder", "00000000-0000-0000-0000-000000000000");
      else if (field.type === "bytes") I18n.attribute(input, "placeholder", msg("Octets en hexadécimal"));
      else if (field.name === "gtin") { input.inputMode = "numeric"; I18n.attribute(input, "placeholder", msg("Code produit de la bobine")); }
      else I18n.attribute(input, "placeholder", msg("Non renseigné"));
    }
    input.id = `${prefix}-${region}-${field.name}`;
    input.dataset.field = field.name;
    input.dataset.region = region;
    input.value = rawValue(field, value);
    input.disabled = protectedRegion;
    input.autocomplete = "off";
    if (field.required === true || field.required === "required") input.required = true;
    input.addEventListener("input", invalidatePreview);
    input.addEventListener("change", invalidatePreview);
    label.append(input);
    if (field.max_length) label.append(node("span", "field-hint", msg("{0} octets{1} maximum", field.max_length, field.type === "bytes" ? "" : " UTF-8")));
    else if (field.type === "enum_array") label.append(node("span", "field-hint", msg("Liste de valeurs au format JSON, par exemple [1, 2].")));
    else if (field.type === "color_lab") label.append(node("span", "field-hint", msg("Trois valeurs au format JSON : [L, a, b].")));
    else if (field.type === "timestamp") label.append(node("span", "field-hint", msg("Date enregistrée en secondes Unix, uniquement si connue.")));
    return label;
  }
  function renderEditorFields(main = {}, aux = {}) {
    for (const region of ["main", "aux"]) {
      const common = $(`editor-${region}`), advanced = $(`editor-${region}-advanced`);
      clear(common); clear(advanced);
      const set = region === "main" ? coreMain : coreAux;
      const locked = state.editorMode === "update" && Boolean(state.editorTag?.protections?.[region]);
      for (const field of state.schema[region] || []) {
        if (!field.name || field.deprecated) continue;
        const value = (region === "main" ? main : aux)[field.name];
        const control = buildField(field, region, value, "editor", locked || ((state.editorMode === "update" || state.qrData) && field.name === "instance_uuid"));
        (set.has(field.name) ? common : advanced).append(control);
      }
    }
  }
  function renderEditorNote() {
    const tag = state.editorTag;
    const note = $("editor-reader-note");
    note.className = "notice";
    if (!tag) I18n.text(note, msg("Relisez le tag présenté pour préparer son écriture."));
    else if (state.editorMode === "create" && !isBlank(tag)) {
      I18n.text(note, isSimulation() ? msg("La création nécessite un tag vierge. Dans le simulateur, choisissez « Créer un tag vierge », ou passez en modification pour corriger cette bobine.") : msg("La création nécessite un tag vierge. Présentez-en un autre, ou choisissez « Modifier un tag existant » pour corriger cette bobine."));
      note.classList.add("warning");
    } else if (state.editorMode === "update" && isBlank(tag)) {
      I18n.text(note, msg("Le tag lu est vierge. Choisissez « Nouveau tag » pour renseigner sa fiche."));
      note.classList.add("warning");
    } else I18n.text(note, msg("{0} · {1}. Vérifiez les données avant écriture.", state.editorMode === "create" ? msg("Création sur tag vierge") : msg("Modification du tag lu"), tag.uid));
    setText("editor-current-tag", tag ? `${spoolName(tag)} · ${tag.uid}` : msg("Aucun tag lu."));
    const protection = $("editor-protection"); clear(protection);
    if (state.stockSource) {
      protection.append(node("p", "notice", state.stockSource.label_state === "rfid"
        ? msg("Recréation pour {0}. L’ancien tag sera remplacé après écriture et relecture réussies. Le numéro et la date d’entrée sont conservés.", state.stockSource.spool_number)
        : msg("Création pour {0}. La fiche d’inventaire et sa date d’entrée sont conservées.", state.stockSource.spool_number)));
    }
    if (tag?.protections?.main) protection.append(node("span", "status-chip locked", msg("Matériau protégé")));
    if (tag?.protections?.aux) protection.append(node("span", "status-chip locked", msg("Suivi protégé")));
    syncControls();
  }
  function setEditorMode(mode, tag = state.currentTag) {
    if ($("camera-dialog").open) $("camera-dialog").close();
    state.qrEpoch += 1;
    state.editorMode = mode;
    state.qrData = null; state.stockSource = null;
    state.editorTag = clone(tag);
    state.sourceQR = null;
    state.sourceFavorite = null;
    $("mode-create").classList.toggle("selected", mode === "create");
    $("mode-update").classList.toggle("selected", mode === "update");
    $("mode-create").setAttribute("aria-pressed", String(mode === "create"));
    $("mode-update").setAttribute("aria-pressed", String(mode === "update"));
    $("sources-card").hidden = mode !== "create";
    renderEditorFields(mode === "update" ? tag?.main || {} : {}, mode === "update" ? tag?.aux || {} : {});
    invalidatePreview(); renderEditorNote();
  }
  function parseInput(input, field) {
    const text = input.value.trim();
    if (!text) return null;
    if (field.type === "enum" && field.options?.length) {
      const option = field.options.find((item) => String(item.value) === text);
      return option ? option.value : (/^-?\d+$/.test(text) ? Number(text) : text);
    }
    if (["number", "int", "timestamp"].includes(field.type)) {
      const value = Number(text);
      if (!Number.isFinite(value) || (["int", "timestamp"].includes(field.type) && !Number.isSafeInteger(value))) throw new Error(msg("{0} : saisissez un nombre valide.", nameOf(field.name)));
      return value;
    }
    if (["enum_array", "color_lab"].includes(field.type)) {
      let value;
      try { value = JSON.parse(text); } catch { throw new Error(msg("{0} : la liste doit être au format JSON.", nameOf(field.name))); }
      if (!Array.isArray(value)) throw new Error(msg("{0} : une liste de valeurs est attendue.", nameOf(field.name)));
      return value;
    }
    return text;
  }
  function readFields(container, baseline = {}, update = false) {
    const result = {main: {}, aux: {}};
    for (const input of container.querySelectorAll("[data-field]")) {
      if (input.disabled) continue;
      const region = input.dataset.region, name = input.dataset.field;
      const field = fieldDef(region, name);
      if (!field) continue;
      if (update && input.value === rawValue(field, baseline?.[region]?.[name])) continue;
      const value = parseInput(input, field);
      const before = baseline?.[region]?.[name] ?? null;
      if (update) { if (JSON.stringify(value) !== JSON.stringify(before)) result[region][name] = value; }
      else if (value !== null) result[region][name] = value;
    }
    return result;
  }
  function applyMain(main) {
    for (const [name, value] of Object.entries(main || {})) {
      if (individualFields.has(name)) continue;
      const input = $("editor-form").querySelector(`[data-region="main"][data-field="${CSS.escape(name)}"]`);
      if (!input || input.disabled) continue;
      const field = fieldDef("main", name);
      if (input.tagName === "SELECT" && ![...input.options].some((option) => option.value === String(value))) {
        const unknown = node("option", "", msg("Valeur inconnue : {0}", value)); unknown.value = String(value); input.append(unknown);
      }
      input.value = rawValue(field, value);
    }
    invalidatePreview();
  }
  function renderPreview(preview) {
    state.preview = preview;
    const container = $("preview-changes"); clear(container);
    if (preview.tag?.inventory) {
      const item = preview.tag.inventory;
      container.append(node("p", "notice", preview.recreation
        ? msg("Bobine {0} : le nouveau tag remplacera l’association à {1}. Vérifiez les données ci-dessous avant de confirmer.", item.spool_number, item.uid)
        : msg("Bobine {0} : ce tag sera associé à sa fiche d’inventaire après vérification.", item.spool_number)));
    }
    const changes = preview.changes || [];
    if (!changes.length) container.append(node("p", "muted", msg("Aucune différence sur les champs renseignés.")));
    else {
      const table = node("table", "change-table");
      const head = node("thead"), tr = node("tr");
      for (const label of [msg("Champ"), msg("Avant"), msg("Après")]) tr.append(node("th", "", label));
      head.append(tr); table.append(head);
      const body = node("tbody");
      for (const change of changes) {
        const row = node("tr");
        row.append(node("td", "", nameOf(change.name)), node("td", "", displayValue(change.region || "main", change.name, change.before)), node("td", "", displayValue(change.region || "main", change.name, change.after)));
        body.append(row);
      }
      table.append(body); container.append(table);
    }
    setText("preview-mode", isSimulation() ? msg("Écriture simulée") : msg("Écriture NFC"));
    $("write-preview").hidden = false;
    syncControls();
    $("write-preview").scrollIntoView({behavior: "auto", block: "nearest"});
  }
  async function prepareWrite() {
    if (!$("editor-form").reportValidity()) return;
    if (!state.editorTag) throw new Error(msg("Relisez d’abord le tag présenté."));
    if ($("qr-text").value.trim() && !state.sourceQR) throw new Error(msg("Analysez le QR avant de préparer l’écriture, ou effacez-le pour une saisie manuelle."));
    const values = readFields($("editor-form"), state.qrData || state.editorTag, Boolean(state.qrData) || state.editorMode === "update");
    const preview = await post("/api/reader/prepare", {
      mode: state.editorMode, main: values.main, aux: values.aux,
      expected_uid: state.editorTag.uid, expected_revision: state.editorTag.revision,
      ...(state.sourceQR ? {qr_raw: state.sourceQR} : {}),
      ...(state.sourceFavorite != null ? {favorite_id: state.sourceFavorite} : {}),
      ...(state.stockSource ? {inventory_id: state.stockSource.id, inventory_version: state.stockSource.version, inventory_recreate: state.stockSource.label_state === "rfid"} : {}),
    });
    renderPreview(preview);
  }
  async function writePreview() {
    if (!state.preview) return;
    const id = state.preview.preview_id;
    try {
      const response = await post("/api/reader/write", {preview_id: id});
      invalidatePreview();
      if (!response.verified) throw new Error(msg("L’écriture n’a pas été confirmée par relecture. Relisez le tag avant toute nouvelle opération."));
      setCurrentTag(response.tag);
      setEditorMode("update", response.tag);
      await refreshStock(); await refreshSimulator();
      notify(response.simulation ? msg("Écriture simulée terminée et vérifiée par relecture.") : msg("Tag écrit et vérifié par relecture."));
    } catch (error) {
      invalidatePreview();
      throw new Error(msg("{0} Relisez le tag avant de préparer une nouvelle écriture.", error.message));
    }
  }

  function renderInventory() {
    const items = state.inventory.filter((item) => item.in_stock !== false);
    const completed = state.inventory.filter((item) => item.completed_at);
    const archived = state.inventoryView === "completed";
    setText("stock-count", String(items.length));
    setText("completed-count", String(completed.length));
    const known = items.filter((item) => typeof item.remaining_weight === "number");
    setText("stock-weight", known.length ? grams(known.reduce((total, item) => total + item.remaining_weight, 0)) : "—");
    setText("favorite-count", String(state.favorites.length));
    const search = $("inventory-search").value.trim().toLocaleLowerCase("fr");
    const source = archived ? [...completed].sort((a, b) => b.completed_at.localeCompare(a.completed_at)) : items;
    const numberSearch = /^b\d{1,18}$/i.test(search) ? "b" + search.slice(1).replace(/^0+(?=\d)/, "").padStart(4, "0") : null;
    const visible = source.filter((item) => !search || (numberSearch ? item.spool_number?.toLowerCase() === numberSearch : [item.spool_number, item.notes, item.uid, ...Object.values(item.main || {}), ...Object.values(item.aux || {})].join(" ").toLocaleLowerCase("fr").includes(search)));
    setText("inventory-title", archived ? msg("Bobines terminées") : msg("Vos bobines"));
    for (const [id, active] of [["inventory-stock", !archived], ["inventory-archives", archived]]) {
      $(id).classList.toggle("selected", active); $(id).setAttribute("aria-pressed", String(active));
    }
    $("inventory-sort").disabled = archived;
    $("inventory-sort").closest("label").hidden = archived;
    const container = $("inventory-list"); clear(container);
    if (!visible.length) {
      const empty = node("div", "table-empty");
      empty.append(node("strong", "", search ? msg("Aucune bobine ne correspond") : archived ? msg("Aucune bobine terminée") : msg("Votre inventaire est prêt à être rempli")), node("span", "", search ? msg("Essayez une autre marque ou un autre matériau.") : archived ? msg("Les bobines marquées comme terminées apparaîtront ici.") : canControl() ? msg("Ajoutez une bobine emballée ou lisez un tag RFID pour entrer une bobine au stock.") : msg("Ajoutez une bobine emballée pour préparer son QR, ou consultez les bobines déjà enregistrées.")));
      container.append(empty);
    } else {
      const table = node("table", "inventory-table");
      const header = node("thead"), headrow = node("tr");
      for (const text of [msg("BOBINE"), msg("MATIÈRE"), archived ? msg("DERNIER RESTANT CONNU") : msg("RESTANT"), msg("ENTRÉE EN STOCK"), archived ? msg("TERMINÉE LE") : msg("DERNIÈRE LECTURE"), msg("ACTIONS")]) headrow.append(node("th", "", text));
      header.append(headrow); table.append(header);
      const tbody = node("tbody");
      for (const item of visible) {
        const row = node("tr");
        const identityCell = node("td");
        const identityButton = node("button", "table-link spool-cell"); identityButton.type = "button";
        I18n.attribute(identityButton, "aria-label", msg("Détail de {0}", spoolTitle(item)));
        const description = node("span"); description.append(node("span", "spool-number", item.spool_number), node("strong", "", spoolName(item)), node("small", "", item.main?.brand_name || msg("Marque non renseignée")));
        if (item.notes) description.append(node("small", "spool-notes-indicator", msg("Notes disponibles")));
        description.append(node("span", `status-chip ${item.usage_state === "stock" ? "qr-stock" : "in-stock"}`, usageState(item)), node("small", "", identification(item)));
        identityButton.append(swatch(item.main?.primary_color), description); identityButton.addEventListener("click", () => showDetail(item)); identityCell.append(identityButton);
        const materialCell = node("td", "", item.main?.material_type == null ? "—" : displayValue("main", "material_type", item.main.material_type));
        const weightCell = node("td", "", grams(item.remaining_weight));
        if (item.remaining_estimated && item.remaining_weight != null) weightCell.append(node("small", "muted", msg(" · estimé")));
        const dateCell = node("td", "table-date", formatDate(archived ? item.completed_at : item.last_seen_at));
        const arrivalCell = node("td", "table-date", stockDate(item)); arrivalCell.append(node("small", "", stockAge(item)));
        const actionCell = node("td");
        const actions = node("div", "table-actions");
        const label = node("button", "button secondary small", msg("Étiquette QR")); label.type = "button";
        label.addEventListener("click", () => task(label, () => openLabel(item))); actions.append(label);
        if (!archived) {
          const finish = completionButton(item, "button secondary small");
          const remove = node("button", "button secondary small", msg("Retirer")); remove.type = "button";
          I18n.attribute(remove, "aria-label", msg("Retirer {0} de l’inventaire", spoolName(item)));
          remove.addEventListener("click", () => task(remove, async () => { await removeInventory(item); notify(msg("Bobine retirée de l’inventaire. Son tag est conservé.")); }));
          actions.append(finish, remove);
        }
        actionCell.append(actions); row.append(identityCell, materialCell, weightCell, arrivalCell, dateCell, actionCell); tbody.append(row);
      }
      table.append(tbody); container.append(table);
    }
    const unknown = items.length - known.length;
    setText("inventory-footnote", archived ? msg("Archives : {0} bobine{1}. Fiches conservées, de la fin la plus récente à la plus ancienne.", completed.length, completed.length === 1 ? "" : "s") : msg("{0} bobine{1} dans l’inventaire{2}. Le retrait conserve les données du tag.", items.length, items.length === 1 ? "" : "s", unknown ? msg(" · quantité restante inconnue pour {0} bobine{1}", unknown, unknown === 1 ? "" : "s") : ""));
  }
  async function refreshStock() {
    const response = await api(`/api/inventory?include_removed=true&sort=${encodeURIComponent($("inventory-sort").value)}`);
    state.inventory = response.items || [];
    if (state.currentTag) {
      const entry = state.inventory.find((item) => item.uid === state.currentTag.uid && item.instance_uuid === state.currentTag.instance_uuid);
      state.currentTag.inventory = state.currentTag.association_pending ? null : entry || null;
      renderReader();
    }
    renderInventory();
    if ($("detail-dialog").open && state.detailItem) {
      const current = state.inventory.find((item) => item.id === state.detailItem.id);
      if (current) showDetail(current);
    }
  }
  function completionButton(item, className = "button secondary") {
    const button = node("button", className, msg("Marquer comme terminée")); button.type = "button";
    I18n.attribute(button, "aria-label", msg("Marquer {0} comme terminée", spoolName(item)));
    button.addEventListener("click", () => task(button, async () => {
      await post(`/api/inventory/${encodeURIComponent(item.id)}/complete`, {version: item.version});
      await refreshStock(); notify(msg("Bobine terminée et archivée. Le compteur a été actualisé."));
    }));
    return button;
  }
  async function removeInventory(item) {
    const response = await post(`/api/inventory/${encodeURIComponent(item.id)}/remove`, {version: item.version});
    if (state.currentTag?.inventory?.id === item.id) state.currentTag.inventory = {id: item.id, in_stock: false, version: response.version ?? item.version};
    await refreshStock();
  }
  function showDetail(item) {
    state.detailItem = item;
    setText("detail-title", spoolTitle(item));
    renderSpoolNotes(item);
    const content = $("detail-content"); clear(content);
    const summary = node("div", "detail-summary");
    for (const [label, value] of [[msg("Utilisation"), usageState(item)], [msg("Identification"), identification(item)], [msg("Entrée en stock"), stockDate(item)], [msg("Ancienneté"), stockAge(item)], [msg("Restant connu"), grams(item.remaining_weight)], [msg("Consommé"), grams(item.aux?.consumed_weight)], [msg("Dernière lecture"), formatDate(item.last_seen_at)]]) {
      const box = node("div"); box.append(node("span", "", label), node("strong", "", value)); summary.append(box);
    }
    content.append(summary, node("p", "mono muted", item.uid || ""));
    if (item.label_state === "rfid") content.append(node("p", "notice", msg("Un tag RFID existe déjà pour cette bobine.")));
    if (item.completed_at) {
      const ended = node("div"); ended.append(node("span", "", msg("Terminée le")), node("strong", "", formatDate(item.completed_at))); summary.append(ended);
      content.append(node("p", "fine-print", msg("Fiche archivée : les dernières données connues sont conservées. Le tag RFID reste inchangé.")));
    }
    const actions = node("div", "detail-actions"), label = node("button", "button secondary", msg("Afficher / imprimer le QR")); label.type = "button";
    label.addEventListener("click", () => task(label, async () => { $("detail-dialog").close(); await openLabel(item); })); actions.append(label);
    if (item.in_stock && !item.completed_at) {
      const usage = node("button", "button secondary", item.usage_state === "stock" ? msg("Passer en service") : msg("Remettre en stock")); usage.type = "button"; usage.id = "detail-change-usage";
      usage.addEventListener("click", () => task(usage, async () => {
        try {
          const updated = await post(`/api/inventory/${encodeURIComponent(item.id)}/usage`, {version: item.version, usage_state: item.usage_state === "stock" ? "in_service" : "stock"});
          await refreshStock();
          notify(updated.usage_state === "stock" ? msg("Bobine remise en stock. Son tag et ses données sont conservés.") : msg("Bobine passée en service. Son tag et ses données sont conservés."));
        } catch (error) { if (error.status === 409) await refreshStock(); throw error; }
      }));
      actions.append(usage);
      content.append(node("p", "fine-print", msg("Le statut En stock ou En service est indépendant du QR ou du tag RFID et reste enregistré après une nouvelle lecture.")));
    }
    const model = node("button", "button secondary", msg("Créer un modèle")); model.type = "button"; model.id = "detail-create-model";
    model.addEventListener("click", () => task(model, async () => {
      const profile = await post(`/api/inventory/${encodeURIComponent(item.id)}/model-source`, {version: item.version});
      if (!$("detail-dialog").open || state.detailItem?.id !== item.id || !canBrowse()) return;
      $("detail-dialog").close();
      openFavorite(null, {name: profile.suggested_name || "", main: profile.main, kind: "model", warnings: profile.warnings});
    })); actions.append(model);
    if (canControl() && item.in_stock && !item.completed_at) {
      const prepare = node("button", "button primary", item.label_state === "rfid" ? msg("Recréer le tag RFID") : msg("Créer le tag RFID")); prepare.type = "button";
      prepare.addEventListener("click", () => task(prepare, () => prepareInventoryTag(item))); actions.append(prepare);
    }
    if (!item.completed_at) actions.append(completionButton(item));
    content.append(actions);
    const fields = $("detail-fields") || node("div", "field-tables"); renderFieldTables(fields, item);
    if (!$("detail-fields")) content.append(fields);
    if (!$("detail-dialog").open) $("detail-dialog").showModal();
  }

  function notesSavedText(updated) { return updated ? msg("Notes enregistrées le {0}.", formatDate(updated)) : msg("Aucune note enregistrée."); }
  async function refreshInventoryNotes(force = false) {
    if (!canBrowse() || state.inventoryNotesBusy) return;
    state.inventoryNotesBusy = true; syncControls();
    try {
      const response = await api("/api/inventory/notes");
      if (!canBrowse()) return;
      if (!force && state.inventoryNotesDirty) {
        if (response.revision !== state.inventoryNotes?.revision) setText("inventory-notes-result", msg("Le carnet a changé ailleurs. Votre saisie est conservée. Rechargez les notes pour consulter la dernière version."));
        return;
      }
      state.inventoryNotes = response; state.inventoryNotesDirty = false;
      $("inventory-notes").value = response.text;
      setText("inventory-notes-result", notesSavedText(response.updated_at));
    } finally { state.inventoryNotesBusy = false; syncControls(); }
  }
  async function saveInventoryNotes() {
    if (!state.inventoryNotes || state.inventoryNotesBusy) return;
    state.inventoryNotesBusy = true; syncControls();
    try {
      state.inventoryNotes = await api("/api/inventory/notes", {method: "PUT", body: {text: $("inventory-notes").value, revision: state.inventoryNotes.revision}});
      state.inventoryNotesDirty = false;
      setText("inventory-notes-result", notesSavedText(state.inventoryNotes.updated_at));
      notify(msg("Carnet commun enregistré sur la station."));
    } catch (error) { setText("inventory-notes-result", error.message); throw error; }
    finally { state.inventoryNotesBusy = false; syncControls(); }
  }
  function renderSpoolNotes(item, force = false) {
    let draft = state.spoolNotesDrafts.get(item.id);
    if (!draft || force || (!draft.dirty && !draft.busy)) {
      draft = {text: item.notes || "", originalText: item.notes || "", revision: item.notes_revision, dirty: false, busy: false};
      state.spoolNotesDrafts.set(item.id, draft);
    }
    if ($("spool-notes").value !== draft.text) $("spool-notes").value = draft.text;
    setText("spool-notes-result", draft.dirty && item.notes_revision !== draft.revision ? msg("Ces notes ont changé ailleurs. Votre saisie est conservée. Rechargez les notes pour consulter la dernière version.") : draft.dirty ? msg("Modifications non enregistrées.") : notesSavedText(item.notes_updated_at));
    syncControls();
  }
  async function saveSpoolNotes() {
    const item = state.detailItem, draft = item && state.spoolNotesDrafts.get(item.id);
    if (!draft || draft.busy) return;
    draft.busy = true; syncControls();
    try {
      const updated = await api(`/api/inventory/${encodeURIComponent(item.id)}/notes`, {method: "PUT", body: {text: draft.text, revision: draft.revision}});
      state.spoolNotesDrafts.delete(item.id);
      state.detailItem = updated;
      renderSpoolNotes(updated, true);
      await refreshStock();
      notify(msg("Notes de la bobine enregistrées."));
    } catch (error) { setText("spool-notes-result", error.message); throw error; }
    finally { draft.busy = false; syncControls(); }
  }

  async function prepareInventoryTag(item) {
    const current = await api(`/api/inventory/${encodeURIComponent(item.id)}`);
    if (!canControl() || !current.in_stock || current.completed_at || !["qr", "rfid"].includes(current.label_state)) throw new Error(msg("Cette bobine ne peut pas préparer un nouveau tag. Rechargez sa fiche."));
    if ($("detail-dialog").open) $("detail-dialog").close();
    if ($("label-dialog").open) $("label-dialog").close();
    setEditorMode("create", null);
    state.stockSource = current; state.qrData = current; state.sourceQR = null;
    $("qr-text").value = "";
    renderEditorFields(current.main, current.aux); showTab("write", true);
    renderEditorNote();
    setText("editor-reader-note", msg("Fiche {0} chargée depuis l’inventaire. Posez un tag vierge puis cliquez sur Relire le tag présenté.", current.spool_number));
    notify(msg("Fiche {0} chargée sans scan QR. Vérifiez les données avant écriture.", current.spool_number));
  }
  function renderFavorites() {
    const container = $("favorites-list"); clear(container);
    const select = $("favorite-select"), previous = select.value; clear(select);
    const blank = node("option", "", msg("Choisir un favori")); blank.value = ""; select.append(blank);
    if (!state.favorites.length) {
      const empty = node("div", "table-empty");
      empty.append(node("strong", "", msg("Gardez vos matériaux habituels à portée de main")), node("span", "", msg("Enregistrez une fiche de référence pour préremplir vos prochains tags."))); container.append(empty);
    }
    for (const favorite of state.favorites) {
      const option = node("option", "", favorite.name); option.value = favorite.id; select.append(option);
      const card = node("article", "favorite-card"), identity = node("div", "favorite-identity");
      identity.append(swatch(favorite.main?.primary_color), node("strong", "", favorite.name));
      identity.append(node("span", "status-chip", favorite.kind === "model" ? msg("Modèle") : msg("Favori")));
      const summary = [favorite.main?.brand_name, favorite.main?.material_type == null ? null : displayValue("main", "material_type", favorite.main.material_type), favorite.main?.nominal_netto_full_weight == null ? null : grams(favorite.main.nominal_netto_full_weight)].filter(Boolean).join(" · ");
      card.append(identity, node("p", "", summary || msg("Fiche à compléter")));
      const actions = node("div", "card-actions");
      const edit = node("button", "button secondary small", msg("Modifier")); edit.type = "button"; edit.addEventListener("click", () => openFavorite(favorite)); actions.append(edit);
      if (canControl()) {
        const use = node("button", "button secondary small", msg("Utiliser")); use.type = "button";
        use.addEventListener("click", () => { setEditorMode("create"); applyMain(favorite.main); state.sourceFavorite = favorite.id; state.sourceQR = null; $("favorite-select").value = favorite.id; showTab("write"); notify(msg("Fiche « {0} » chargée. Complétez les données propres à la bobine.", favorite.name)); }); actions.append(use);
      }
      const addStock = node("button", "button secondary small", msg("Nouvelle bobine en stock")); addStock.type = "button";
      addStock.addEventListener("click", () => openPackaged(favorite)); actions.append(addStock);
      const remove = node("button", "button danger small", msg("Supprimer")); remove.type = "button";
      remove.addEventListener("click", () => openDeleteFavorite(favorite)); actions.append(remove);
      card.append(actions); container.append(card);
    }
    if (state.favorites.some((item) => String(item.id) === previous)) select.value = previous;
    setText("favorite-count", String(state.favorites.length));
    syncControls();
  }
  async function refreshFavorites() {
    const response = await api("/api/favorites"); state.favorites = response.items || [];
    const exists = (id) => state.favorites.some((item) => item.id === id);
    if (state.sourceFavorite && !exists(state.sourceFavorite)) state.sourceFavorite = null;
    // Keep entered spool data when a template disappears in another client.
    for (const option of [...$("packaged-favorite").options]) if (option.value && !exists(option.value)) option.remove();
    renderFavorites();
  }
  function openDeleteFavorite(favorite) {
    state.deletingFavorite = clone(favorite);
    setText("delete-favorite-name", favorite.name);
    $("delete-favorite-dialog").showModal();
    $("cancel-delete-favorite").focus();
    syncControls();
  }
  async function deleteFavorite() {
    const favorite = state.deletingFavorite;
    if (!favorite) return;
    try {
      await api(`/api/favorites/${encodeURIComponent(favorite.id)}`, {method: "DELETE", body: {version: favorite.version}});
    } catch (error) {
      if ([404, 409].includes(error.status)) {
        $("delete-favorite-dialog").close();
        await refreshFavorites();
      }
      throw error;
    }
    $("delete-favorite-dialog").close();
    await refreshFavorites();
    notify(msg("Fiche supprimée de la bibliothèque. Les bobines existantes sont conservées."));
  }
  function openFavorite(favorite = null, seed = null) {
    state.editingFavorite = favorite;
    const profile = favorite || seed;
    setText("favorite-dialog-title", favorite ? msg("Modifier la fiche") : seed ? msg("Nouveau modèle") : msg("Nouvelle fiche"));
    $("favorite-kind").value = profile?.kind || "favorite";
    $("favorite-name").value = profile?.name || "";
    $("favorite-source-note").hidden = !seed;
    setText("favorite-result", ""); $("favorite-result").hidden = true; clear($("favorite-source-warnings"));
    for (const warning of seed?.warnings || []) $("favorite-source-warnings").append(node("p", "notice warning", warning));
    clear($("favorite-fields")); clear($("favorite-fields-advanced"));
    for (const field of state.schema.main || []) {
      if (!field.name || field.deprecated || individualFields.has(field.name)) continue;
      const control = buildField(field, "main", profile?.main?.[field.name], "favorite");
      // A favorite may be a partial template; material_class is required when writing the actual tag.
      control.querySelector("[data-field]").required = false;
      control.querySelector(".required-star")?.remove();
      (coreMain.has(field.name) ? $("favorite-fields") : $("favorite-fields-advanced")).append(control);
    }
    $("favorite-dialog").showModal();
    $("favorite-name").focus();
  }
  function modelSourceNote(message, type = "") {
    const note = $("model-source-note"); I18n.text(note, message);
    note.hidden = !message; note.className = `notice ${type}`;
    clear($("model-source-matches"));
  }
  function openModelSource() {
    state.modelSourceEpoch += 1; state.modelSourceBusy = false;
    $("model-source-qr").value = ""; modelSourceNote("");
    $("model-source-dialog").showModal(); syncControls();
  }
  function useModelSource(profile, warnings = []) {
    $("model-source-dialog").close();
    openFavorite(null, {name: profile.suggested_name || "", main: profile.main, kind: "model", warnings});
  }
  async function inspectModelSource(source = "qr", expected = null) {
    const text = $("model-source-qr").value, epoch = ++state.modelSourceEpoch;
    if (source === "qr" && !text.trim()) { modelSourceNote(msg("Scannez ou collez un code."), "warning"); return; }
    state.modelSourceBusy = true; syncControls(); modelSourceNote(source === "rfid" ? msg("Lecture du tag pour préparer le modèle…") : msg("Analyse du code en cours…"));
    try {
      const result = await post("/api/library/model-source", {source, ...(source === "qr" ? {text} : expected || {})});
      if (epoch !== state.modelSourceEpoch || !$("model-source-dialog").open || !canBrowse()
          || (source === "rfid" && !canControl()) || (source === "qr" && $("model-source-qr").value !== text)) return;
      if (result.matches?.length) {
        modelSourceNote(result.message, "warning");
        for (const match of result.matches) {
          const choose = node("button", "button secondary small", match.label || match.suggested_name || msg("Choisir cette référence")); choose.type = "button";
          choose.addEventListener("click", () => useModelSource(match, result.warnings)); $("model-source-matches").append(choose);
        }
      } else useModelSource(result, result.warnings);
    } catch (error) {
      if (epoch === state.modelSourceEpoch && $("model-source-dialog").open) modelSourceNote(error.message, "error");
    } finally {
      if (epoch === state.modelSourceEpoch) { state.modelSourceBusy = false; syncControls(); }
    }
  }
  async function saveFavorite() {
    if (!$("favorite-form").reportValidity()) return;
    const name = $("favorite-name").value.trim();
    if (!name) throw new Error(msg("Donnez un nom à votre fiche."));
    const fields = readFields($("favorite-form"));
    const existing = state.editingFavorite;
    let response;
    try { response = await api(existing ? `/api/favorites/${encodeURIComponent(existing.id)}` : "/api/favorites", {method: existing ? "PUT" : "POST", body: {name, main: fields.main, kind: $("favorite-kind").value, ...(existing ? {version: existing.version} : {})}}); }
    catch (error) { setText("favorite-result", error.message); $("favorite-result").hidden = false; throw error; }
    $("favorite-dialog").close();
    await refreshFavorites();
    if (response.id) $("favorite-select").value = response.id;
    syncControls(); notify(msg("Fiche enregistrée sur la station."));
  }
  async function inspectQR() {
    const text = $("qr-text").value;
    const epoch = state.qrEpoch;
    if (!text.trim()) throw new Error(msg("Scannez ou collez d’abord le contenu d’un QR ou d’un code produit."));
    const result = await post("/api/qr/inspect", {text});
    if (state.qrEpoch !== epoch || $("qr-text").value !== text || state.editorMode !== "create") return;
    state.sourceQR = result.raw ?? text;
    state.sourceFavorite = null;
    invalidatePreview();
    const note = $("qr-result"); note.hidden = false;
    note.className = `notice${result.kind === "unknown" || result.kind === "url" ? " warning" : ""}`;
    I18n.text(note, result.message || msg("Contenu analysé. Vérifiez les données avant écriture."));
    const matches = $("qr-matches"); clear(matches);
    if (result.kind === "opt_station") {
      state.qrData = result; state.stockSource = result.inventory || null;
      renderEditorFields(result.main, result.aux); renderEditorNote();
    } else {
      state.qrData = null; state.stockSource = null;
      if (["prusament", "prusa_product"].includes(result.kind)) renderEditorFields(result.main, result.aux || {});
      else if (result.main && Object.keys(result.main).length) applyMain(result.main);
    }
    for (const warning of result.warnings || []) matches.append(node("p", "notice warning", warning));
    for (const match of result.matches || []) {
      const data = match.main || match.fields || {};
      const label = match.label || match.name || data.material_name || msg("Fiche de référence");
      const row = node("div", "qr-match"); row.append(node("span", "", label));
      const apply = node("button", "button secondary small", msg("Charger cette fiche")); apply.type = "button";
      apply.addEventListener("click", () => { applyMain(data); state.sourceQR = result.raw || text; notify(msg("Données de référence chargées. Vérifiez et complétez la fiche.")); }); row.append(apply); matches.append(row);
    }
  }

  function renderPackagedFields(main = {}, aux = {}) {
    for (const region of ["main", "aux"]) {
      clear($(`packaged-${region}`)); clear($(`packaged-${region}-advanced`));
      const common = region === "main" ? coreMain : coreAux;
      for (const field of state.schema[region] || []) {
        if (!field.name || field.name === "instance_uuid") continue;
        const control = buildField(field, region, (region === "main" ? main : aux)[field.name], "packaged");
        $(`packaged-${region}${common.has(field.name) ? "" : "-advanced"}`).append(control);
      }
    }
  }
  function openPackaged(favorite = null) {
    state.packagedEpoch += 1; state.packagedAnalyzing = false;
    state.packagedUUID = newUUID(); state.packagedSource = null; state.packagedQR = null;
    $("packaged-qr").value = ""; packagedNote("");
    const select = $("packaged-favorite"); clear(select);
    const empty = node("option", "", msg("Saisie manuelle")); empty.value = ""; select.append(empty);
    for (const item of state.favorites) { const option = node("option", "", item.name); option.value = item.id; select.append(option); }
    select.value = favorite?.id || "";
    renderPackagedFields(favorite?.main || {}, {});
    $("packaged-dialog").showModal(); syncControls();
  }
  function packagedNote(message, type = "") {
    const note = $("packaged-source-note");
    I18n.text(note, message); note.hidden = !message; note.className = `notice ${type}`;
    clear($("packaged-source-warnings")); clear($("packaged-matches"));
  }
  async function inspectPackagedQR() {
    const text = $("packaged-qr").value;
    const epoch = ++state.packagedEpoch;
    if (!text.trim()) { packagedNote(msg("Scannez ou collez un code."), "warning"); return; }
    state.packagedSource = null; state.packagedAnalyzing = true; syncControls();
    packagedNote(msg("Analyse du code en cours…"));
    let report;
    try { report = await post("/api/qr/inspect", {text}); }
    catch (error) {
      if (state.packagedEpoch === epoch && $("packaged-dialog").open) packagedNote(error.message, "error");
      return;
    } finally {
      if (state.packagedEpoch === epoch) { state.packagedAnalyzing = false; syncControls(); }
    }
    if (state.packagedEpoch !== epoch || $("packaged-qr").value !== text || !$("packaged-dialog").open) return;
    if (report.inventory) {
      $("packaged-dialog").close(); await openLabel(report.inventory);
      notify(msg("La fiche existante de cette bobine a été retrouvée.")); return;
    }
    state.packagedQR = report; state.packagedSource = text;
    if (Object.keys(report.main || {}).length) {
      $("packaged-favorite").value = "";
      renderPackagedFields(report.main, report.aux || {});
    }
    packagedNote(report.message, ["url", "unknown"].includes(report.kind) ? "warning" : "success");
    for (const warning of report.warnings || []) $("packaged-source-warnings").append(node("p", "notice warning", warning));
    for (const match of report.matches || []) {
      const choose = node("button", "button secondary small", match.label || match.main?.material_name || msg("Choisir cette référence")); choose.type = "button";
      choose.addEventListener("click", () => { renderPackagedFields(match.main || {}, {}); }); $("packaged-matches").append(choose);
    }
  }
  async function savePackaged() {
    if (!$("packaged-form").reportValidity()) return;
    if ($("packaged-qr").value.trim() && !state.packagedSource) throw new Error(msg("Analysez le code avant d’enregistrer, ou effacez-le pour une saisie manuelle."));
    const isOPT = state.packagedQR?.kind === "opt_station";
    const fields = readFields($("packaged-form"), isOPT ? state.packagedQR : {}, isOPT);
    if (!isOPT) fields.main.instance_uuid = state.packagedUUID;
    const item = await post("/api/inventory/packaged", {...fields,
      ...(state.packagedSource ? {qr_raw: state.packagedSource} : {}),
      ...($("packaged-favorite").value ? {favorite_id: $("packaged-favorite").value} : {})});
    $("packaged-dialog").close(); await refreshStock();
    notify(msg("Bobine ajoutée au stock, sous QR. Aucun tag RFID n’a été écrit."));
    try { await openLabel(item); }
    catch (error) { notify(msg("La bobine est bien au stock. {0}", error.message), true); }
  }
  async function openLabel(item) {
    const current = await api(`/api/inventory/${encodeURIComponent(item.id)}`);
    const preview = await api(`/api/inventory/${encodeURIComponent(item.id)}/label?version=${current.version}`);
    state.labelPreview = preview; state.labelRequestId = newUUID();
    setText("label-title", spoolTitle(preview.item));
    $("label-image").src = preview.image;
    $("label-text").value = preview.text;
    $("label-download").href = preview.image;
    $("label-download").download = `opt-station-${preview.item.spool_number || preview.item.instance_uuid}.png`;
    setText("label-meta", msg("{0} × {1} mm · QR complet · {2}", preview.width_mm, preview.height_mm, identification(preview.item)));
    setText("label-result", preview.print_enabled ? msg("Une étiquette sera imprimée sur l’imprimante USB du Pi.") : msg("Aperçu prêt. Réglez l’imprimante d’étiquettes dans Configuration pour l’impression USB; le téléchargement reste disponible."));
    setText("label-print", msg("Imprimer une étiquette"));
    $("label-prepare").hidden = preview.item.label_state !== "qr" || Boolean(preview.item.completed_at);
    $("label-associate").hidden = preview.item.label_state !== "qr" || Boolean(preview.item.completed_at);
    $("label-restore").hidden = preview.item.in_stock || Boolean(preview.item.completed_at);
    if (!$("label-dialog").open) $("label-dialog").showModal(); syncControls();
  }
  async function printLabel() {
    const preview = state.labelPreview;
    if (!preview) return;
    setText("label-result", msg("Impression en cours sur le Pi… Ne relancez pas une autre demande."));
    try {
      const result = await post(`/api/inventory/${encodeURIComponent(preview.item.id)}/print`, {
        version: preview.item.version, settings_revision: preview.settings_revision,
        image_sha256: preview.image_sha256, request_id: state.labelRequestId});
      setText("label-result", result.detail || msg("Demande en cours. Vérifiez l’état avant de réimprimer."));
      if (result.status !== "pending") {
        state.labelRequestId = newUUID();
        setText("label-print", result.status === "complete" ? msg("Réimprimer une étiquette") : msg("Réessayer après vérification"));
      } else setText("label-print", msg("Vérifier la demande en cours"));
    } catch (error) {
      setText("label-result", msg("{0} Vérifiez l’étiquette avant de réimprimer. Le même identifiant de demande est conservé.", error.message));
      setText("label-print", msg("Vérifier la demande")); throw error;
    }
  }
  async function prepareLabelTag() {
    const preview = state.labelPreview;
    if (!preview) return;
    $("label-dialog").close(); setEditorMode("create", null); showTab("write", true);
    $("qr-text").value = preview.text; state.qrEpoch += 1;
    await inspectQR();
    setText("editor-reader-note", msg("Fiche QR complète chargée. Posez un tag vierge, puis cliquez sur Relire le tag présenté avant de vérifier l’écriture."));
    notify(msg("Fiche QR chargée. Présentez un tag vierge, puis relisez-le avant l’écriture."));
  }
  async function associateLabelTag() {
    const item = state.labelPreview?.item;
    if (!item) return;
    const tag = await api("/api/reader/tag");
    const result = await post(`/api/inventory/${encodeURIComponent(item.id)}/associate`, {
      version: item.version, expected_uid: tag.uid, expected_revision: tag.revision});
    $("label-dialog").close(); await refreshStock(); showDetail(result);
    notify(msg("Tag relu et associé à la fiche existante. Aucun tag n’a été écrit."));
  }
  async function refreshLabelsSettings() {
    if (!canControl() || state.labelsLoading) return;
    state.labelsLoading = true; syncControls();
    try {
      const result = await api("/api/configuration/labels");
      if (!canControl()) return;
      state.labelsSettings = result; state.labelsDirty = false;
      $("labels-enabled").checked = result.enabled;
      for (const [id, key] of [["labels-model", "model"], ["labels-port", "port"], ["labels-width", "width_mm"], ["labels-height", "height_mm"], ["labels-density", "density"]]) $(id).value = result[key];
      clear($("labels-ports"));
      for (const port of result.ports || []) { const option = node("option"); option.value = port.port; option.label = port.name; $("labels-ports").append(option); }
      setText("labels-state", result.enabled ? msg("Impression activée") : msg("Désactivée"));
      setText("labels-access", msg("Réglages du périphérique raccordé au Pi. La détection ne déclenche aucune impression."));
    } finally { state.labelsLoading = false; syncControls(); }
  }
  async function saveLabelsSettings() {
    if (!$("labels-settings-form").reportValidity() || !state.labelsSettings) return false;
    const result = await api("/api/configuration/labels", {method: "PUT", body: {
      revision: state.labelsSettings.revision, enabled: $("labels-enabled").checked,
      model: $("labels-model").value, port: $("labels-port").value.trim(),
      width_mm: Number($("labels-width").value), height_mm: Number($("labels-height").value), density: Number($("labels-density").value)}});
    state.labelsSettings = result; state.labelsDirty = false;
    setText("labels-state", result.enabled ? msg("Impression activée") : msg("Désactivée"));
    setText("labels-result", msg("Réglages d’étiquettes enregistrés sur le Pi.")); syncControls(); return true;
  }
  $("new-packaged").addEventListener("click", () => openPackaged());
  $("packaged-form").addEventListener("submit", (event) => { event.preventDefault(); task($("packaged-save"), savePackaged); });
  $("packaged-favorite").addEventListener("change", () => {
    state.packagedEpoch += 1; state.packagedAnalyzing = false;
    state.packagedQR = null; state.packagedSource = null; $("packaged-qr").value = "";
    const favorite = state.favorites.find((item) => item.id === $("packaged-favorite").value);
    renderPackagedFields(favorite?.main || {}, {}); packagedNote(favorite ? msg("Favori « {0} » chargé. Complétez les données propres à la bobine.", favorite.name) : ""); syncControls();
  });
  $("packaged-qr").addEventListener("input", () => {
    state.packagedEpoch += 1; state.packagedAnalyzing = false; packagedNote("");
    if (state.packagedQR?.kind === "opt_station") renderPackagedFields({}, {});
    state.packagedSource = null; state.packagedQR = null; syncControls();
  });
  $("packaged-inspect").addEventListener("click", (event) => task(event.currentTarget, inspectPackagedQR));
  $("packaged-camera").addEventListener("click", (event) => task(event.currentTarget, async () => {
    state.cameraTarget = "stock"; $("camera-dialog").showModal(); await beginCamera();
  }));
  $("inventory-sort").addEventListener("change", () => task(null, refreshStock));
  $("label-print").addEventListener("click", (event) => task(event.currentTarget, printLabel));
  $("label-prepare").addEventListener("click", (event) => task(event.currentTarget, prepareLabelTag));
  $("label-restore").addEventListener("click", (event) => task(event.currentTarget, async () => {
    const item = state.labelPreview.item;
    const restored = await post(`/api/inventory/${encodeURIComponent(item.id)}/restore`, {version: item.version});
    await refreshStock(); await openLabel(restored); notify(msg("Bobine remise au stock avec sa date d’entrée d’origine."));
  }));
  $("label-associate").addEventListener("click", (event) => task(event.currentTarget, associateLabelTag));
  $("labels-settings-form").addEventListener("input", () => { state.labelsDirty = true; setText("labels-result", msg("Modifications à enregistrer.")); syncControls(); });
  $("labels-settings-form").addEventListener("change", () => { state.labelsDirty = true; syncControls(); });
  $("labels-settings-form").addEventListener("submit", (event) => { event.preventDefault(); task($("labels-save"), saveLabelsSettings); });
  $("labels-reload").addEventListener("click", (event) => task(event.currentTarget, refreshLabelsSettings));
  $("labels-probe").addEventListener("click", (event) => task(event.currentTarget, async () => {
    if (state.labelsDirty && !await saveLabelsSettings()) return;
    const result = await post("/api/labels/probe");
    setText("labels-result", result.status === "identified" ? msg("{0}, identifiant {1}. Détection réussie sans impression.", result.name, result.model_id) : result.detail);
  }));
  document.addEventListener("opt-station-tab", (event) => {
    if (event.detail.tab === "configuration" && canControl() && !state.labelsDirty) task(null, refreshLabelsSettings);
  });
  document.addEventListener("opt-station-status", () => {
    if (!canControl()) {
      state.labelsSettings = null; state.labelsDirty = false; $("labels-settings-fields").disabled = true;
      setText("labels-access", msg("Activez l’accès complet pour régler et utiliser l’imprimante d’étiquettes."));
    } else if (state.activeTab === "configuration" && !state.labelsSettings) task(null, refreshLabelsSettings);
  });

  const cameraActive = (scan) => Boolean(scan?.active) || ["starting", "scanning", "stopping"].includes(scan?.state);
  function releaseCamera(id) {
    return fetch(`/api/camera/scans/${encodeURIComponent(id)}`, {
      method: "DELETE", credentials: "same-origin", keepalive: true,
      headers: {"Content-Type": "application/json"}, body: "{}",
    }).then((response) => { if (!response.ok && response.status !== 404) throw new Error(msg("L’arrêt de la caméra n’a pas été confirmé. Le scan s’arrêtera automatiquement.")); });
  }
  function closeCamera() {
    const scan = state.cameraScan;
    state.cameraEpoch += 1;
    clearTimeout(state.cameraTimer);
    state.cameraScan = null;
    state.cameraStarting = false;
    $("camera-preview").removeAttribute("src");
    if (cameraActive(scan)) releaseCamera(scan.id).catch((error) => notify(error.message, true));
    syncControls();
  }
  function renderCamera(scan) {
    setText("camera-message", scan.message);
    $("camera-message").className = `notice${scan.state === "found" ? " success" : ["error", "timeout"].includes(scan.state) ? " warning" : ""}`;
    setText("camera-help", scan.model === "ov5647" ? msg("Cette caméra a une mise au point fixe. Déplacez la bobine jusqu’à ce que le QR soit net, puis immobilisez-la sous une bonne lumière.") : msg("Présentez le QR face à la caméra, sous une bonne lumière. Ajustez la distance jusqu’à obtenir une image nette."));
    setText("camera-timer", scan.state === "scanning" ? msg("Encore {0} s · arrêt automatique après lecture ou à la fin de l’essai.", scan.remaining_seconds) : "");
    $("camera-stop").hidden = !cameraActive(scan);
    $("camera-retry").hidden = cameraActive(scan);
    if (scan.preview_ready && state.cameraFrame !== scan.frames) {
      const preview = $("camera-preview");
      preview.src = `/api/camera/scans/${encodeURIComponent(scan.id)}/preview?v=${scan.frames}`;
      preview.hidden = false;
      $("camera-placeholder").hidden = true;
      state.cameraFrame = scan.frames;
    }
    const resultsKey = `${scan.id}:${JSON.stringify(scan.codes || [])}`;
    if (scan.state === "found" && state.cameraResults !== resultsKey) {
      state.cameraResults = resultsKey;
      const container = $("camera-codes"); clear(container);
      for (const [index, code] of (scan.codes || []).entries()) {
        const card = node("div", "camera-code-card");
        card.append(node("strong", "", scan.codes.length > 1 ? `QR ${index + 1}` : msg("Contenu du QR")), node("p", "mono camera-code-text", code.text));
        const use = node("button", "button primary", msg("Utiliser ce code")); use.type = "button";
        use.addEventListener("click", () => task(use, async () => {
          if (state.cameraTarget === "model") {
            $("camera-dialog").close();
            $("model-source-qr").value = code.text; await inspectModelSource("qr");
          } else if (state.cameraTarget === "stock") {
            $("camera-dialog").close();
            $("packaged-qr").value = code.text; await inspectPackagedQR();
            $("packaged-source-note").scrollIntoView({behavior: "auto", block: "nearest"});
          } else {
            $("qr-text").value = code.text; state.qrEpoch += 1; await inspectQR();
            $("camera-dialog").close();
            $("qr-result").scrollIntoView({behavior: "auto", block: "nearest"});
          }
        }));
        card.append(use); container.append(card);
      }
    }
    syncControls();
  }
  async function pollCamera(epoch) {
    if (epoch !== state.cameraEpoch || !state.cameraScan) return;
    try {
      const scan = await api(`/api/camera/scans/${encodeURIComponent(state.cameraScan.id)}`);
      if (epoch !== state.cameraEpoch) return;
      state.cameraScan = scan;
      renderCamera(scan);
      if (cameraActive(scan)) state.cameraTimer = setTimeout(() => pollCamera(epoch), 500);
    } catch (error) {
      if (epoch !== state.cameraEpoch) return;
      const scan = state.cameraScan;
      if (scan) releaseCamera(scan.id).catch(() => {});
      state.cameraScan = null;
      setText("camera-message", error.message);
      $("camera-message").className = "notice warning";
      setText("camera-timer", "");
      $("camera-stop").hidden = true;
      $("camera-retry").hidden = false;
      syncControls();
    }
  }
  async function beginCamera() {
    const epoch = ++state.cameraEpoch;
    state.cameraStarting = true;
    state.cameraScan = null;
    state.cameraFrame = null;
    state.cameraResults = null;
    clearTimeout(state.cameraTimer);
    clear($("camera-codes"));
    $("camera-preview").hidden = true;
    $("camera-preview").removeAttribute("src");
    $("camera-placeholder").hidden = false;
    $("camera-stop").hidden = false;
    $("camera-retry").hidden = true;
    setText("camera-timer", "");
    setText("camera-message", msg("Ouverture de la caméra…"));
    syncControls();
    try {
      const scan = await post("/api/camera/scans");
      if (epoch !== state.cameraEpoch) { await releaseCamera(scan.id); return; }
      state.cameraScan = scan;
      renderCamera(scan);
      state.cameraTimer = setTimeout(() => pollCamera(epoch), 250);
    } catch (error) {
      if (epoch === state.cameraEpoch) {
        setText("camera-message", error.message);
        $("camera-message").className = "notice warning";
        $("camera-stop").hidden = true;
        $("camera-retry").hidden = false;
      }
      throw error;
    } finally {
      if (epoch === state.cameraEpoch) { state.cameraStarting = false; syncControls(); }
    }
  }

  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.addEventListener("click", () => showTab(button.dataset.tab));
    button.addEventListener("keydown", (event) => {
      if (!["ArrowDown", "ArrowUp", "ArrowRight", "ArrowLeft", "Home", "End"].includes(event.key)) return;
      const tabs = [...document.querySelectorAll("[data-tab]")].filter((tab) => !tab.disabled);
      const index = tabs.indexOf(button);
      let next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (index + (["ArrowDown", "ArrowRight"].includes(event.key) ? 1 : -1) + tabs.length) % tabs.length;
      event.preventDefault(); showTab(tabs[next].dataset.tab, true);
    });
  });
  document.querySelectorAll("[data-close-dialog]").forEach((button) => button.addEventListener("click", () => $(button.dataset.closeDialog).close()));
  $("read-tag").addEventListener("click", (event) => task(event.currentTarget, async () => { await scan(); notify(isSimulation() ? msg("Tag simulé lu. Aucune écriture NFC effectuée.") : msg("Tag lu.")); }));
  $("refresh-all").addEventListener("click", (event) => task(event.currentTarget, async () => {
    state.status = await api("/api/status"); renderStatus();
    if (canBrowse()) await Promise.all([refreshStock(), refreshFavorites(), refreshSimulator(), refreshInventoryNotes()]);
    if (state.activeTab === "configuration") await refreshConfiguration(true);
    else if (state.activeTab === "printer") document.dispatchEvent(new CustomEvent("opt-printer-refresh"));
    else if (canControl() && state.status.reader?.connected && state.status.reader?.present) await scan();
  }));
  $("refresh-inventory").addEventListener("click", (event) => task(event.currentTarget, () => Promise.all([refreshStock(), refreshInventoryNotes()])));
  $("inventory-notes").addEventListener("input", () => { state.inventoryNotesDirty = $("inventory-notes").value !== state.inventoryNotes?.text; setText("inventory-notes-result", state.inventoryNotesDirty ? msg("Modifications non enregistrées.") : notesSavedText(state.inventoryNotes?.updated_at)); syncControls(); });
  $("inventory-notes-form").addEventListener("submit", (event) => { event.preventDefault(); task($("inventory-notes-save"), saveInventoryNotes); });
  $("inventory-notes-reload").addEventListener("click", (event) => task(event.currentTarget, () => refreshInventoryNotes(true)));
  $("spool-notes").addEventListener("input", () => {
    const draft = state.detailItem && state.spoolNotesDrafts.get(state.detailItem.id);
    if (draft) { draft.text = $("spool-notes").value; draft.dirty = draft.text !== draft.originalText; }
    setText("spool-notes-result", draft?.dirty ? msg("Modifications non enregistrées.") : notesSavedText(state.detailItem?.notes_updated_at)); syncControls();
  });
  $("spool-notes-form").addEventListener("submit", (event) => { event.preventDefault(); task($("spool-notes-save"), saveSpoolNotes); });
  $("spool-notes-reload").addEventListener("click", (event) => task(event.currentTarget, async () => {
    if (!state.detailItem) return;
    const item = await api(`/api/inventory/${encodeURIComponent(state.detailItem.id)}`);
    state.detailItem = item; renderSpoolNotes(item, true);
  }));
  $("inventory-search").addEventListener("input", renderInventory);
  for (const [id, view] of [["inventory-stock", "stock"], ["inventory-archives", "completed"]]) {
    $(id).addEventListener("click", () => { state.inventoryView = view; renderInventory(); });
  }
  $("inventory-toggle").addEventListener("click", (event) => task(event.currentTarget, async () => {
    const tag = state.currentTag;
    if (!tag) return;
    if (tag.inventory?.in_stock) {
      await removeInventory(tag.inventory); notify(msg("Bobine retirée du stock. Le tag reste inchangé."));
    } else {
      const entry = await post("/api/inventory/add", {expected_uid: tag.uid, expected_revision: tag.revision});
      tag.inventory = {id: entry.id, version: entry.version, in_stock: true};
      await refreshStock(); notify(msg("Bobine ajoutée à l’inventaire."));
    }
    renderReader();
  }));
  $("confirm-tag-association").addEventListener("click", (event) => task(event.currentTarget, async () => {
    const tag = state.currentTag, pending = tag?.association_pending;
    if (!pending) return;
    await post(`/api/inventory/${encodeURIComponent(pending.id)}/associate`, {
      expected_uid: tag.uid, expected_revision: tag.revision, version: pending.version, recreate: true});
    await scan();
    notify(msg("Tag relu et associé à la fiche existante. Aucun tag n’a été écrit."));
  }));
  $("edit-current").addEventListener("click", () => { setEditorMode("update", state.currentTag); showTab("write"); });
  $("mode-create").addEventListener("click", () => setEditorMode("create"));
  $("mode-update").addEventListener("click", () => setEditorMode("update"));
  $("load-current").addEventListener("click", (event) => task(event.currentTarget, async () => { const tag = await scan(); if (state.editorMode === "update") setEditorMode("update", tag); else { state.editorTag = clone(tag); renderEditorNote(); } notify(msg("Tag relu. Vérifiez la fiche avant de préparer l’écriture.")); }));
  $("editor-form").addEventListener("submit", (event) => { event.preventDefault(); task($("prepare-write"), prepareWrite); });
  $("confirm-write").addEventListener("click", (event) => task(event.currentTarget, writePreview));
  $("favorite-select").addEventListener("change", syncControls);
  $("apply-favorite").addEventListener("click", () => { const favorite = state.favorites.find((item) => String(item.id) === $("favorite-select").value); if (favorite) { if (state.qrData) { state.qrData = null; state.stockSource = null; renderEditorFields({}, {}); } $("qr-text").value = ""; applyMain(favorite.main); state.sourceFavorite = favorite.id; state.sourceQR = null; notify(msg("Fiche « {0} » chargée. Complétez les données de la bobine.", favorite.name)); } });
  $("inspect-qr").addEventListener("click", (event) => task(event.currentTarget, inspectQR));
  $("camera-open").addEventListener("click", (event) => task(event.currentTarget, async () => { state.cameraTarget = "editor"; $("camera-dialog").showModal(); await beginCamera(); }));
  $("camera-retry").addEventListener("click", (event) => task(event.currentTarget, beginCamera));
  $("camera-stop").addEventListener("click", (event) => task(event.currentTarget, async () => {
    if (!state.cameraScan) return;
    const epoch = state.cameraEpoch;
    const scan = await api(`/api/camera/scans/${encodeURIComponent(state.cameraScan.id)}`, {method: "DELETE", body: {}});
    if (epoch === state.cameraEpoch) { state.cameraScan = scan; renderCamera(scan); }
  }));
  $("camera-close").addEventListener("click", () => $("camera-dialog").close());
  $("camera-dialog").addEventListener("close", closeCamera);
  window.addEventListener("pagehide", closeCamera);
  $("qr-text").addEventListener("input", () => {
    state.qrEpoch += 1;
    const hadSpoolQR = Boolean(state.qrData);
    state.sourceQR = null; state.qrData = null; state.stockSource = null;
    if (hadSpoolQR) renderEditorFields({}, {});
    $("qr-result").hidden = true;
    clear($("qr-matches"));
    invalidatePreview();
  });
  $("qr-text").addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); task($("inspect-qr"), inspectQR); } });
  $("new-favorite").addEventListener("click", () => openFavorite());
  $("library-source-open").addEventListener("click", openModelSource);
  $("model-from-tag").addEventListener("click", () => {
    const tag = state.currentTag;
    if (!tag || !canControl()) return;
    openModelSource(); inspectModelSource("rfid", {expected_uid: tag.uid, expected_revision: tag.revision});
  });
  $("model-source-rfid").addEventListener("click", () => inspectModelSource("rfid"));
  $("model-source-inspect").addEventListener("click", () => inspectModelSource("qr"));
  $("model-source-qr").addEventListener("input", () => { state.modelSourceEpoch += 1; state.modelSourceBusy = false; modelSourceNote(""); syncControls(); });
  $("model-source-qr").addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); inspectModelSource("qr"); } });
  $("model-source-camera").addEventListener("click", (event) => task(event.currentTarget, async () => {
    state.cameraTarget = "model"; $("camera-dialog").showModal(); await beginCamera();
  }));
  $("model-source-dialog").addEventListener("close", () => { state.modelSourceEpoch += 1; state.modelSourceBusy = false; syncControls(); });
  $("favorite-form").addEventListener("submit", (event) => { event.preventDefault(); task($("save-favorite"), saveFavorite); });
  $("confirm-delete-favorite").addEventListener("click", (event) => task(event.currentTarget, deleteFavorite));
  $("delete-favorite-dialog").addEventListener("close", () => { state.deletingFavorite = null; syncControls(); });
  $("sim-select").addEventListener("click", (event) => task(event.currentTarget, async () => { if (!$("sim-tag").value) return; setCurrentTag(await post("/api/simulator/select", {uid: $("sim-tag").value})); await refreshStock(); notify(msg("Tag simulé présenté au lecteur.")); }));
  $("sim-blank").addEventListener("click", (event) => task(event.currentTarget, async () => { const tag = await post("/api/simulator/blank"); setCurrentTag(tag); setEditorMode("create", tag); await refreshSimulator(); notify(msg("Nouveau tag simulé vierge présenté. Préparez sa fiche dans Écriture.")); }));
  $("sim-consume").addEventListener("click", (event) => task(event.currentTarget, async () => {
    const amount = Number($("sim-amount").value);
    if (!Number.isFinite(amount) || amount <= 0) throw new Error(msg("Indiquez une consommation positive en grammes."));
    setCurrentTag(await post("/api/simulator/consume", {amount_g: amount})); await refreshStock();
    notify(msg("Consommation simulée sur le tag, comme après son passage dans l’imprimante."));
  }));

  document.addEventListener("opt-station-language", () => {
    numberFormat = new Intl.NumberFormat(I18n.locale(), {maximumFractionDigits: 2});
    if (!state.status) return;
    renderStatus(); renderReader(); renderEditorNote(); renderInventory(); renderFavorites();
    if ($("detail-dialog").open && state.detailItem) showDetail(state.detailItem);
  });

  document.addEventListener("opt-station-library-changed", () => task(null, refreshFavorites));

  async function start() {
    syncControls();
    try {
      const status = await api("/api/status");
      state.status = status;
      renderStatus();
      state.previousRemoteAccess = canBrowse();
      if (!canBrowse()) return;
      state.schema = await api("/api/schema");
      setEditorMode("create");
      await Promise.all([refreshStock(), refreshFavorites(), refreshSimulator(), refreshInventoryNotes()]);
      if (!status.power?.pending && canControl() && status.reader?.connected && status.reader?.present) await scan();
    } catch (error) {
      setText("station-label", msg("Connexion interrompue"));
      setText("configuration-mode-badge", msg("Indisponible"));
      setText("configuration-hardware-message", msg("Actualisez après avoir vérifié que l’application est démarrée."));
      setText("reader-status", msg("Station injoignable"));
      notify(error.message, true);
    }
  }
  start();
  let statusRefreshPending = false;
  const statusRefresh = setInterval(async () => {
    if (!state.status || statusRefreshPending || document.visibilityState !== "visible") return;
    statusRefreshPending = true;
    try {
      const next = await api("/api/status");
      if (next.mode !== state.status.mode) return;
      const libraryChanged = next.library_revision !== state.status.library_revision;
      const completedChanged = next.completed_spools_count !== state.status.completed_spools_count;
      const inventoryChanged = next.inventory_revision !== state.status.inventory_revision;
      const notesChanged = next.inventory_notes_revision !== state.status.inventory_notes_revision;
      if (!next.reader?.connected || (state.status.reader?.present && !next.reader?.present)) invalidatePreview();
      state.status = next;
      renderStatus();
      if (libraryChanged && canBrowse()) await refreshFavorites();
      if ((completedChanged || inventoryChanged) && canBrowse()) await refreshStock();
      if (notesChanged && canBrowse()) await refreshInventoryNotes();
      if (state.previousRemoteAccess === false && canBrowse()) {
        state.schema = await api("/api/schema");
        setEditorMode("create");
        await Promise.all([refreshStock(), refreshFavorites(), refreshSimulator(), refreshConfiguration(), refreshInventoryNotes()]);
      }
      state.previousRemoteAccess = canBrowse();
    } catch { document.dispatchEvent(new CustomEvent("opt-station-offline")); }
    finally { statusRefreshPending = false; }
  }, 5000);
  window.addEventListener("pagehide", () => clearInterval(statusRefresh));
})();
