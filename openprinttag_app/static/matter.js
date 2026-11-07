"use strict";

(() => {
  const I18N = window.OPT_I18N, msg = I18N.msg;
  const $ = (name) => document.getElementById("matter-" + name);
  const text = (name, value) => I18N.text($(name), value);
  const settingsPath = "/api/configuration/matter";
  let access = false, tab = "inventory", epoch = 0, powerPending = false;
  let draft = null, discovery = null, setupBusy = false;
  let status = null, statusBusy = false, actionBusy = false, actionSequence = 0;
  let pendingOff = null;

  function element(tag, className, value) {
    const node = document.createElement(tag);
    node.className = className;
    if (value !== undefined) I18N.text(node, value);
    return node;
  }

  async function request(path, method = "GET", body = null, timeout = 12000) {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), timeout);
    try {
      const options = {method, signal: controller.signal, cache: "no-store", credentials: "same-origin"};
      if (body !== null) {
        options.headers = {"Content-Type": "application/json"};
        options.body = JSON.stringify(body);
      }
      const response = await fetch(path, options);
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "");
      return data;
    } finally { clearTimeout(timer); }
  }

  const key = (row) => row.node_id + "/" + row.endpoint;
  const binding = (row) => key(row) + "/" + row.identity;
  const channel = (row) => msg("Appareil {0} · canal {1}", row.node_id, row.endpoint);
  const state = (on) => on === true ? msg("En marche") : on === false ? msg("Éteint") : msg("Indisponible");
  const offline = () => msg("Le contrôleur Matter du Pi ne répond pas.");
  const transportError = (error) => error.name === "AbortError" || error instanceof TypeError || error instanceof SyntaxError;
  const errorMessage = (error, fallback) => transportError(error) || !error.message ? fallback : I18N.message(error.message);

  function setupControls() {
    const disabled = !access || setupBusy || powerPending;
    $("access").hidden = access;
    $("discover").disabled = disabled;
    $("settings-fields").disabled = disabled || !draft;
    $("pairing").hidden = !access || !discovery;
    $("pair-fields").disabled = disabled || !discovery;
    $("network-only").disabled = !discovery?.bluetooth;
    if (!discovery?.bluetooth) $("network-only").checked = true;
    $("wifi").hidden = $("network-only").checked;
  }

  function renderSetup() {
    setupControls();
    const list = $("settings-devices");
    list.replaceChildren();
    $("enabled").checked = Boolean(draft?.enabled);
    if (!draft) return;
    const configured = new Map(draft.devices.map(row => [binding(row), row]));
    const matches = discovery && (!draft.fabric || draft.fabric === discovery.fabric);
    const discovered = matches ? discovery.devices : [];
    const rows = new Map(discovered.map(row => [binding(row), row]));
    for (const row of configured.values()) {
      if (!rows.has(binding(row))) rows.set(binding(row), row);
    }
    if (discovery && !matches) {
      list.append(element("p", "notice warning", msg("Le contrôleur Matter a changé. Retirez les anciens appareils pour choisir les nouveaux.")));
    }
    for (const [id, row] of rows) {
      const saved = configured.get(id);
      const item = element("div", "matter-setting");
      const select = element("label", "printer-check");
      const checkbox = element("input", "");
      checkbox.type = "checkbox";
      checkbox.checked = Boolean(saved);
      checkbox.addEventListener("change", () => {
        const previous = draft.devices.find(device => key(device) === key(row));
        draft.devices = draft.devices.filter(device => key(device) !== key(row));
        if (checkbox.checked) {
          draft.fabric = discovery.fabric;
          draft.devices.push({node_id: row.node_id, endpoint: row.endpoint, identity: row.identity,
            name: row.name || String(channel(row)), role: previous?.role || ""});
        }
        if (!draft.devices.length) draft.fabric = null;
        renderSetup();
      });
      select.append(checkbox, element("strong", "", row.name || channel(row)));
      if (row.name) select.append(element("span", "fine-print", channel(row)));
      item.append(select);
      if (saved) {
        const fields = element("div", "form-grid");
        const name = element("input", "");
        name.value = saved.name;
        name.required = true;
        name.maxLength = 80;
        name.addEventListener("input", () => { saved.name = name.value; });
        const role = element("select", "");
        role.required = true;
        for (const [value, label] of [["", msg("Choisir un usage")], ["accessory", msg("Accessoire · marche et arrêt")],
          ["printer", msg("Prise de l’imprimante · arrêt protégé")]]) {
          const option = element("option", "", label);
          option.value = value;
          role.append(option);
        }
        role.value = saved.role;
        role.addEventListener("change", () => { saved.role = role.value; });
        const nameLabel = element("label", "field");
        nameLabel.append(element("span", "", msg("Nom affiché")), name);
        const roleLabel = element("label", "field");
        roleLabel.append(element("span", "", msg("Usage de l’appareil")), role);
        fields.append(nameLabel, roleLabel);
        item.append(fields);
      }
      list.append(item);
    }
  }

  async function setup(work) {
    if (!access || setupBusy || powerPending) return;
    const current = epoch;
    setupBusy = true;
    setupControls();
    try { await work(current); }
    catch (error) {
      if (current === epoch) text("setup-result", errorMessage(error, offline()));
    } finally {
      if (current === epoch) {
        setupBusy = false;
        renderSetup();
      }
    }
  }

  async function loadSettings(current) {
    const saved = await request(settingsPath);
    if (current === epoch && saved.revision !== draft?.revision) draft = saved;
  }

  async function discover(current) {
    const found = await request("/api/matter/discovery");
    if (current === epoch) {
      discovery = found;
      text("setup-result", found.devices.length ? msg("Contrôleur Matter connecté.")
        : msg("Contrôleur Matter connecté. Associez un appareil pour commencer."));
    }
  }

  function pendingPrinter() {
    if (!pendingOff || !status?.enabled || pendingOff.revision !== status.revision) return null;
    return status.devices.find(row => key(row) === pendingOff.key && row.role === "printer") || null;
  }

  function renderOffDialog() {
    if (!$("off-dialog").open) return;
    const row = pendingPrinter();
    const reason = row?.power_off_block_reason || (row?.on === true && row.power_off_block_reason === null
      ? "" : msg("Les appareils Matter ont changé. Actualisez la liste."));
    $("off-confirm").disabled = !access || actionBusy || powerPending || Boolean(reason);
    text("off-blocked", reason ? I18N.message(reason) : "");
  }

  function prepareOff(row) {
    pendingOff = {key: key(row), revision: status.revision};
    text("off-title", msg("Éteindre la prise « {0} » ?", row.name));
    $("off-dialog").showModal();
    renderOffDialog();
  }

  function renderStatus() {
    $("panel").hidden = !access || !status?.enabled;
    $("refresh").disabled = actionBusy || powerPending;
    renderOffDialog();
    const list = $("devices");
    list.replaceChildren();
    if ($("panel").hidden) return;
    text("status", status.message ? I18N.message(status.message) : status.devices.length ? ""
      : msg("Sélectionnez des appareils dans Paramètres → Appareils Matter."));
    for (const row of status.devices) {
      const item = element("div", "matter-control");
      const title = element("div", "matter-device-name", row.name);
      title.append(element("span", "status-chip" + (row.on === true ? " in-stock" : ""), state(row.on)));
      const on = row.on !== true;
      const printerOff = row.role === "printer" && !on;
      const blocked = printerOff && row.power_off_block_reason !== null;
      const label = on ? msg("Allumer") : msg("Éteindre");
      const button = element("button", printerOff ? "button danger small" : "button secondary small", label);
      button.type = "button";
      button.disabled = actionBusy || powerPending || typeof row.on !== "boolean" || blocked;
      I18N.attribute(button, "aria-label", on ? msg("Allumer {0}", row.name) : msg("Éteindre {0}", row.name));
      button.addEventListener("click", () => printerOff ? prepareOff(row) : void command(row, on));
      item.append(title, button);
      if (blocked && row.power_off_block_reason) {
        item.append(element("p", "fine-print matter-off-note", I18N.message(row.power_off_block_reason)));
      }
      list.append(item);
    }
  }

  async function refreshStatus() {
    if (!access || tab !== "printer" || statusBusy || actionBusy || document.hidden) return;
    const current = epoch, sequence = actionSequence;
    statusBusy = true;
    try {
      const next = await request("/api/matter/status");
      if (current === epoch && sequence === actionSequence && JSON.stringify(next) !== JSON.stringify(status)) {
        status = next;
        renderStatus();
      }
    } catch (error) {
      if (current === epoch && sequence === actionSequence && status) {
        status = {...status, message: String(errorMessage(error, offline())),
          devices: status.devices.map(row => ({...row, on: null}))};
        renderStatus();
      }
    } finally { if (current === epoch) statusBusy = false; }
  }

  async function command(row, on) {
    if (!access || actionBusy || powerPending || !status?.enabled) return;
    const current = epoch;
    actionSequence++;
    actionBusy = true;
    text("action-result", msg("Commande Matter en cours…"));
    renderStatus();
    try {
      const result = await request("/api/matter/command", "POST",
        {revision: status.revision, node_id: row.node_id, endpoint: row.endpoint, on}, 30000);
      if (current === epoch) {
        row.on = result.on;
        text("action-result", msg("État de l’appareil vérifié."));
      }
    } catch (error) {
      if (current === epoch) {
        row.on = null;
        text("action-result", errorMessage(error, msg("État Matter à vérifier. Actualisez avant de renvoyer une commande.")));
      }
    } finally {
      if (current === epoch) {
        actionBusy = false;
        renderStatus();
      }
    }
  }

  $("enabled").addEventListener("change", () => { draft.enabled = $("enabled").checked; });
  $("off-dialog").addEventListener("close", () => { if (!$("off-dialog").open) pendingOff = null; });
  $("off-confirm").addEventListener("click", () => {
    const row = pendingPrinter();
    if (!row || row.on !== true || row.power_off_block_reason !== null || $("off-confirm").disabled) return;
    $("off-dialog").close();
    void command(row, false);
  });
  $("network-only").addEventListener("change", setupControls);
  $("refresh").addEventListener("click", () => void refreshStatus());
  $("discover").addEventListener("click", () => void setup(async (current) => {
    text("setup-result", msg("Recherche des appareils Matter…"));
    discovery = null;
    await loadSettings(current);
    if (current === epoch) await discover(current);
  }));
  $("settings-form").addEventListener("submit", (event) => {
    event.preventDefault();
    if (!draft) return;
    void setup(async (current) => {
      const saved = await request(settingsPath, "PUT", draft);
      if (current === epoch) {
        draft = saved;
        text("setup-result", msg("Réglages Matter enregistrés."));
      }
    });
  });
  $("pair-form").addEventListener("submit", (event) => {
    event.preventDefault();
    if (!access || setupBusy || powerPending || !discovery) return;
    const body = {fabric: discovery.fabric, code: $("code").value, network_only: $("network-only").checked};
    if (!body.network_only && $("wifi-ssid").value) {
      body.wifi_ssid = $("wifi-ssid").value;
      body.wifi_password = $("wifi-password").value;
    }
    $("code").value = "";
    $("wifi-password").value = "";
    void setup(async (current) => {
      text("setup-result", msg("Association Matter en cours…"));
      try { await request("/api/matter/pair", "POST", body, 120000); }
      catch (error) {
        if (transportError(error)) {
          throw new Error(String(msg("Association Matter à vérifier. Actualisez la liste des appareils.")));
        }
        throw error;
      }
      if (current !== epoch) return;
      await discover(current);
      if (current === epoch) {
        $("pairing").open = false;
        text("setup-result", msg("Appareil associé. Sélectionnez-le dans la liste."));
      }
    });
  });

  function activeTab() {
    if (tab === "printer") void refreshStatus();
    if (tab === "configuration" && !draft) void setup(loadSettings);
  }

  function setAccess(next) {
    if (next === access) return;
    access = next;
    epoch++;
    if (access) activeTab();
    else {
      draft = discovery = status = null;
      setupBusy = statusBusy = actionBusy = false;
      if ($("off-dialog").open) $("off-dialog").close();
      $("pair-form").reset();
      text("setup-result", "");
      text("action-result", "");
    }
    renderSetup();
    renderStatus();
  }

  document.addEventListener("opt-station-status", (event) => {
    const pending = Boolean(event.detail.power?.pending);
    const changed = pending !== powerPending;
    powerPending = pending;
    setAccess(Boolean(event.detail.access));
    if (changed) {
      setupControls();
      renderStatus();
    }
  });
  document.addEventListener("opt-station-tab", (event) => { tab = event.detail.tab; activeTab(); });
  document.addEventListener("opt-station-offline", () => setAccess(false));
  document.addEventListener("visibilitychange", () => { if (!document.hidden) activeTab(); });
  setInterval(() => void refreshStatus(), 5000);
  setupControls();
})();
