"use strict";
(() => {
  const I18n = window.OPT_I18N, msg = I18n.msg, $ = id => document.getElementById(id);
  let owner = null, generation = 0, busy = false, access = false, browse = false, available = false;
  let scan = null, timer = null, proposal = null, objectURL = null, deleting = null, items = [];
  const text = (id, value) => I18n.text($(id), value);
  const path = current => `/api/photos/${current.kind}/${encodeURIComponent(current.id)}`;
  async function request(url, body, method = "POST") {
    const response = await fetch(url, {method: body === undefined ? "GET" : method,
      credentials: "same-origin", cache: "no-store", signal: AbortSignal.timeout(20000),
      ...(body === undefined ? {} : {headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)})});
    const value = await response.json();
    if (!response.ok) throw new Error(I18n.message(value.detail || msg("Impossible de charger les photos.")));
    return value;
  }
  function controls() {
    const full = items.length >= 8;
    $("photos-file").disabled = !browse || busy || full;
    $("photos-camera").disabled = !access || !available || busy || full;
    $("photos-save").disabled = !browse || busy || !proposal || full;
    $("photos-refresh").disabled = !browse || busy;
    $("photos-discard").disabled = busy;
    $("photos-access").hidden = access;
    $("photos-delete-yes").disabled = !browse || busy;
    $("photos-delete-no").disabled = busy;
    $("photos-gallery").querySelectorAll("button").forEach(button => { button.disabled = !browse || busy; });
  }
  async function release(id) { if (id) try { await request(`/api/camera/scans/${encodeURIComponent(id)}`, {}, "DELETE"); } catch {} }
  function discard() {
    clearTimeout(timer); release(scan); scan = null; proposal = null;
    if (objectURL) URL.revokeObjectURL(objectURL);
    objectURL = null; $("photos-preview").removeAttribute("src"); $("photos-proposal").hidden = true;
    $("photos-file").value = "";
  }
  function displayProposal(url) {
    $("photos-preview").src = url; $("photos-proposal").hidden = false;
    text("photos-message", msg("Vérifiez la photo puis joignez-la à la fiche.")); controls();
  }
  function gallery() {
    const root = $("photos-gallery"); root.replaceChildren();
    if (!items.length) { const empty = document.createElement("p"); I18n.text(empty, msg("Aucune photo jointe à cette fiche.")); root.append(empty); }
    for (const item of items) {
      const card = document.createElement("figure"), link = document.createElement("a"), image = document.createElement("img");
      link.href = `${path(owner)}/${encodeURIComponent(item.id)}`; link.target = "_blank"; link.rel = "noopener noreferrer";
      image.src = link.href + "?thumbnail=true"; image.loading = "lazy";
      I18n.attribute(image, "alt", msg("Photo de {0}", owner.title)); link.append(image);
      const caption = document.createElement("figcaption"), date = document.createElement("span"), remove = document.createElement("button");
      date.textContent = new Date(item.created_at).toLocaleDateString(I18n.locale());
      remove.type = "button"; remove.className = "button secondary small"; I18n.text(remove, msg("Supprimer"));
      remove.addEventListener("click", () => { deleting = item.id; $("photos-delete-confirm").hidden = false; $("photos-delete-yes").focus(); });
      caption.append(date, remove); card.append(link, caption); root.append(card);
    }
    controls();
  }
  async function refresh() {
    if (!owner || !browse) return;
    const expected = generation, current = owner;
    try {
      const result = await request(path(current));
      if (generation !== expected) return;
      items = result.items; gallery();
      text("photos-message", items.length >= 8 ? msg("Cette fiche contient déjà 8 photos. Retirez-en une pour en ajouter une autre.") : msg("{0} photo(s) jointe(s).", items.length));
    } catch (error) { if (generation === expected) text("photos-message", error.message); }
  }
  window.OPT_PHOTOS = {open(kind, id, title) {
    generation++; busy = false; discard(); owner = {kind, id, title}; items = []; deleting = null;
    $("photos-title").textContent = title; $("photos-gallery").replaceChildren(); $("photos-delete-confirm").hidden = true;
    text("photos-message", msg("Chargement des photos…"));
    if (!$("photos-dialog").open) $("photos-dialog").showModal(); controls(); refresh();
  }};
  ["photos-close", "photos-done"].forEach(id => $(id).addEventListener("click", () => $("photos-dialog").close()));
  $("photos-dialog").addEventListener("close", () => { generation++; busy = false; discard(); owner = null; });
  $("photos-refresh").addEventListener("click", refresh);
  $("photos-discard").addEventListener("click", () => { generation++; discard(); controls(); text("photos-message", msg("Photo annulée.")); });
  $("photos-file").addEventListener("change", () => {
    if (!browse || busy) return;
    const file = $("photos-file").files[0]; if (!file) return;
    generation++; discard();
    if (file.size > 4 * 1024 * 1024 || !["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
      text("photos-message", msg("Choisissez une image JPEG, PNG ou WebP de moins de 4 Mo.")); controls(); return;
    }
    const expected = generation, reader = new FileReader(); busy = true; controls();
    reader.onload = () => {
      if (generation !== expected) return;
      busy = false; proposal = {image: reader.result}; objectURL = URL.createObjectURL(file); displayProposal(objectURL);
    };
    reader.onerror = () => { if (generation === expected) { busy = false; text("photos-message", msg("La photo est illisible.")); controls(); } };
    reader.readAsDataURL(file);
  });
  async function poll(expected) {
    if (expected !== generation || !scan) return;
    try {
      const result = await request(`/api/camera/scans/${encodeURIComponent(scan)}`);
      if (expected !== generation) return;
      if (result.active) { timer = setTimeout(() => poll(expected), 400); return; }
      busy = false;
      if (result.state === "found" && result.preview_ready) {
        proposal = {scan_id: scan}; displayProposal(`/api/camera/scans/${encodeURIComponent(scan)}/preview`);
      } else { text("photos-message", I18n.message(result.message)); controls(); }
    } catch (error) { if (expected === generation) { busy = false; text("photos-message", error.message); controls(); } }
  }
  $("photos-camera").addEventListener("click", async () => {
    if (!access || busy) return;
    const expected = ++generation; discard(); busy = true; controls(); text("photos-message", msg("Prise de photo…"));
    try {
      const result = await request("/api/camera/photos", {});
      if (expected !== generation) { release(result.id); return; }
      scan = result.id; timer = setTimeout(() => poll(expected), 350);
    } catch (error) { if (expected === generation) { busy = false; text("photos-message", error.message); controls(); } }
  });
  $("photos-save").addEventListener("click", async () => {
    if (!owner || !proposal || busy || !browse) return;
    const expected = generation; busy = true; controls(); text("photos-message", msg("Enregistrement de la photo…"));
    try {
      await request(path(owner), proposal);
      if (expected !== generation) return;
      discard(); await refresh();
    } catch (error) { if (expected === generation) text("photos-message", error.message); }
    finally { if (expected === generation) { busy = false; controls(); } }
  });
  $("photos-delete-no").addEventListener("click", () => { deleting = null; $("photos-delete-confirm").hidden = true; });
  $("photos-delete-yes").addEventListener("click", async () => {
    if (!owner || !deleting || busy || !browse) return;
    const expected = generation; busy = true; controls();
    try {
      await request(`${path(owner)}/${encodeURIComponent(deleting)}`, {}, "DELETE");
      if (expected !== generation) return;
      deleting = null; $("photos-delete-confirm").hidden = true; await refresh();
    } catch (error) { if (expected === generation) text("photos-message", error.message); }
    finally { if (expected === generation) { busy = false; controls(); } }
  });
  document.addEventListener("opt-station-status", event => {
    access = event.detail.access; browse = event.detail.browse; available = Boolean(event.detail.camera?.available);
    if (!browse && $("photos-dialog").open) $("photos-dialog").close();
    else if (!access && proposal?.scan_id) { generation++; busy = false; discard(); }
    controls();
  });
  document.addEventListener("opt-station-language", () => { if (owner) gallery(); });
})();
