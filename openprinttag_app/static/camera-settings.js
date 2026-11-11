"use strict";

(() => {
  const I18N = window.OPT_I18N, msg = I18N.msg;
  const $ = (name) => document.getElementById("camera-settings-" + name);
  const labels = {
    Brightness: () => msg("Luminosité"), Contrast: () => msg("Contraste"),
    Saturation: () => msg("Saturation"), Sharpness: () => msg("Netteté"),
    ExposureValue: () => msg("Correction d’exposition"), AfMode: () => msg("Mise au point automatique"),
  };
  let access = false, powerPending = false, available = false;
  let epoch = 0, scan = null, settings = null, timer = null, busy = false;
  let stopping = Promise.resolve();

  async function request(path, method = "GET", body = null) {
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 12000);
    try {
      const options = {method, cache: "no-store", credentials: "same-origin", signal: controller.signal};
      if (body !== null) {
        options.headers = {"Content-Type": "application/json"};
        options.body = JSON.stringify(body);
      }
      const response = await fetch(path, options);
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "");
      return result;
    } finally { clearTimeout(timeout); }
  }

  function message(value, warning = false) {
    I18N.text($("message"), value);
    $("message").className = "notice" + (warning ? " warning" : "");
  }

  function failure(error) {
    message(error.name === "AbortError" || error instanceof TypeError || !error.message
      ? msg("La caméra ne répond pas. Réessayez dans un instant.") : I18N.message(error.message), true);
  }

  function buttons() {
    const blocked = !access || powerPending || busy;
    $("open").disabled = blocked || !available;
    $("fields").disabled = blocked || !settings;
    $("save").disabled = blocked || !settings?.controls.length;
    $("reset").disabled = blocked || !settings?.controls.length;
    $("restart").disabled = blocked || Boolean(scan?.active);
  }

  function renderSettings() {
    $("controls").replaceChildren();
    for (const option of settings?.controls || []) {
      const row = document.createElement("label"), title = document.createElement("span");
      row.className = "camera-image-control";
      I18N.text(title, labels[option.name]());
      const input = document.createElement("input");
      input.dataset.control = option.name;
      if (option.name === "AfMode") {
        input.type = "checkbox";
        input.checked = settings.values[option.name] === 2;
        row.append(title, input);
      } else {
        input.type = "range";
        input.min = option.min;
        input.max = option.max;
        input.step = option.step;
        input.value = settings.values[option.name];
        const value = document.createElement("output");
        value.textContent = input.value;
        input.addEventListener("input", () => { value.textContent = input.value; });
        row.append(title, input, value);
      }
      $("controls").append(row);
    }
    buttons();
  }

  async function poll(current) {
    if (current !== epoch || !$("dialog").open || !scan) return;
    try {
      const next = await request("/api/camera/scans/" + scan.id);
      if (current !== epoch) return;
      scan = next;
      if (next.preview_ready && ($("image").complete || !$("image").hasAttribute("src"))) {
        $("image").src = "/api/camera/scans/" + next.id + "/preview?t=" + Date.now();
      }
      if (!next.active) message(I18N.message(next.message), next.state === "error");
      buttons();
      if (next.active) timer = setTimeout(() => void poll(current), 650);
    } catch (error) {
      if (current === epoch) { failure(error); stopping = stopScan(); buttons(); }
    }
  }

  async function startPreview(current) {
    const started = await request("/api/camera/previews", "POST", {});
    if (current !== epoch || !$("dialog").open) {
      await request("/api/camera/scans/" + started.id, "DELETE", {});
      return;
    }
    scan = started;
    message(msg("Aperçu caméra en direct."));
    buttons();
    void poll(current);
  }

  async function stopScan() {
    clearTimeout(timer);
    const previous = scan;
    scan = null;
    if (previous) {
      try {
        let result = await request("/api/camera/scans/" + previous.id, "DELETE", {});
        for (let attempt = 0; result.active && attempt < 20; attempt++) {
          await new Promise((resolve) => setTimeout(resolve, 150));
          result = await request("/api/camera/scans/" + previous.id);
        }
      }
      catch (_) { /* The server also bounds camera sessions. */ }
    }
  }

  async function open() {
    if (!access || powerPending || busy || !available) return;
    const current = ++epoch;
    $("dialog").showModal();
    $("image").hidden = true;
    $("placeholder").hidden = false;
    message(msg("Ouverture de la caméra…"));
    busy = true;
    buttons();
    try {
      await stopping;
      const loaded = await request("/api/configuration/camera");
      if (current !== epoch) return;
      settings = loaded;
      renderSettings();
      await startPreview(current);
    } catch (error) { if (current === epoch) failure(error); }
    finally { if (current === epoch) { busy = false; buttons(); } }
  }

  async function save(reset) {
    if (!settings || busy || !access || powerPending) return;
    const current = epoch, controls = {};
    if (!reset) {
      for (const input of $("controls").querySelectorAll("input")) {
        controls[input.dataset.control] = input.type === "checkbox" ? (input.checked ? 2 : 0) : Number(input.value);
      }
    }
    busy = true;
    buttons();
    try {
      const saved = await request("/api/configuration/camera", "PUT",
        {revision: settings.revision, model: settings.model, controls});
      if (current !== epoch) return;
      settings = saved;
      renderSettings();
      message(msg("Réglages de l’image enregistrés."));
    } catch (error) { if (current === epoch) failure(error); }
    finally { if (current === epoch) { busy = false; buttons(); } }
  }

  $("open").addEventListener("click", () => void open());
  $("form").addEventListener("submit", (event) => { event.preventDefault(); void save(false); });
  $("reset").addEventListener("click", () => void save(true));
  $("restart").addEventListener("click", async () => {
    if (busy || scan?.active) return;
    const current = epoch;
    busy = true;
    buttons();
    try { await stopping; await startPreview(current); }
    catch (error) { if (current === epoch) failure(error); }
    finally { if (current === epoch) { busy = false; buttons(); } }
  });
  $("image").addEventListener("load", () => {
    if ($("dialog").open) { $("image").hidden = false; $("placeholder").hidden = true; }
  });
  $("dialog").addEventListener("close", () => {
    epoch++;
    busy = false;
    stopping = stopScan();
    settings = null;
    $("image").removeAttribute("src");
    buttons();
  });
  document.addEventListener("opt-station-status", (event) => {
    access = Boolean(event.detail.access);
    available = Boolean(event.detail.camera?.available);
    powerPending = Boolean(event.detail.power?.pending);
    if ((!access || powerPending) && $("dialog").open) $("dialog").close();
    buttons();
  });
  document.addEventListener("opt-station-offline", () => {
    access = false;
    if ($("dialog").open) $("dialog").close();
    buttons();
  });
  document.addEventListener("opt-station-tab", (event) => {
    if (event.detail.tab !== "configuration" && $("dialog").open) $("dialog").close();
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden && $("dialog").open) $("dialog").close();
  });
  document.addEventListener("opt-station-language", () => { if (settings) renderSettings(); });
  window.addEventListener("pagehide", () => {
    if (scan) void fetch("/api/camera/scans/" + scan.id, {method: "DELETE",
      headers: {"Content-Type": "application/json"}, body: "{}", keepalive: true});
  });
  buttons();
})();
