"use strict";
(() => {
  const I18n = window.OPT_I18N; I18n.init();
  const msg = I18n.msg, $ = id => document.getElementById(id);
  let access = false, available = false, configuration = null, saving = false, dirty = false;
  let busy = false, generation = 0, scan = null, image = null, result = null, imageURL = null, cameraTimer = null;
  const labels = {material_class:msg("Famille de matériau"),material_type:msg("Type de matériau"),material_name:msg("Nom du matériau"),
    brand_name:msg("Marque"),brand_specific_package_id:msg("Référence produit du fabricant"),nominal_netto_full_weight:msg("Poids net initial nominal"),
    primary_color:msg("Couleur principale"),filament_diameter:msg("Diamètre du filament"),density:msg("Densité"),
    min_print_temperature:msg("Température de buse minimale"),max_print_temperature:msg("Température de buse maximale"),
    min_bed_temperature:msg("Température de plateau minimale"),max_bed_temperature:msg("Température de plateau maximale"),
    min_chamber_temperature:msg("Température d’enceinte minimale"),max_chamber_temperature:msg("Température d’enceinte maximale"),country_of_origin:msg("Pays d’origine")};
  const text = (id, value) => I18n.text($(id), value);
  async function request(url, body, method='POST') {
    const response = await fetch(url, {method:body === undefined ? 'GET' : method, credentials:'same-origin',cache:'no-store',
      signal:AbortSignal.timeout(url.endsWith('/analyse') ? 200000 : 15000),
      ...(body === undefined ? {} : {headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})});
    const data = await response.json();
    if (!response.ok) throw new Error(I18n.message(data.detail || msg("L’assistant IA est indisponible.")));
    return data;
  }
  function render() {
    $('ai-open-read').disabled = !access;
    $('ai-open-write').disabled = !access;
    $('ai-settings-fields').disabled = !access || saving;
    $('ai-save').disabled = !access || saving || !configuration;
    $('ai-reload').disabled = !access || saving;
    $('ai-camera').disabled = !access || busy || !available;
    $('ai-file').disabled = !access || busy;
    $('ai-analyse').disabled = !access || busy || !image || !configuration?.enabled || !configuration?.key_saved;
    $('ai-apply').disabled = !access || busy || !result || !Object.keys(result.main).length;
    text('ai-state', configuration?.enabled ? msg("Activé") : msg("Désactivé"));
    text('ai-access-note', !access ? msg("L’assistant IA nécessite l’accès local ou complet.") : configuration?.key_saved ? msg("Une clé IA est enregistrée sur la station.") : msg("Renseignez une clé API dans Configuration pour analyser les étiquettes."));
  }
  async function refresh() {
    if (!access || saving) return;
    saving = true; render();
    try {
      configuration = await request('/api/configuration/assistant');
      if (!dirty) {
        $('ai-enabled').checked = configuration.enabled; $('ai-model').value = configuration.model;
        $('ai-web-search').checked = configuration.web_search; $('ai-key').value = ''; $('ai-clear-key').checked = false;
      }
    } catch(error) { text('ai-settings-result', error.message); }
    finally { saving = false; render(); }
  }
  $('ai-settings-form').addEventListener('input', () => { dirty = true; });
  $('ai-settings-form').addEventListener('submit', async event => {
    event.preventDefault(); if (!access || !configuration || saving) return;
    saving = true; render();
    try {
      configuration = await request('/api/configuration/assistant', {revision:configuration.revision,enabled:$('ai-enabled').checked,
        model:$('ai-model').value.trim(),web_search:$('ai-web-search').checked,api_key:$('ai-key').value.trim() || null,
        clear_key:$('ai-clear-key').checked}, 'PUT');
      dirty = false; $('ai-key').value = ''; $('ai-clear-key').checked = false;
      text('ai-settings-result', msg("Réglages de l’assistant IA enregistrés."));
    } catch(error) { text('ai-settings-result', error.message); }
    finally { saving = false; render(); }
  });
  $('ai-reload').addEventListener('click', () => { dirty = false; refresh(); });
  function releaseImage() {
    if (imageURL) URL.revokeObjectURL(imageURL);
    imageURL = null; $('ai-image').removeAttribute('src'); $('ai-image').hidden = true;
  }
  function showImage(url) { $('ai-image').src = url; $('ai-image').hidden = false; }
  async function releaseScan(id) { if (id) try { await request('/api/camera/scans/'+encodeURIComponent(id), {}, 'DELETE'); } catch {} }
  function clearProposal() { result = null; $('ai-proposal').hidden = true; }
  function open() {
    if (!access) return;
    generation++; image = null; clearProposal(); releaseImage(); $('ai-file').value = '';
    text('ai-message', msg("Prenez une photo nette de l’étiquette avant de lancer l’analyse."));
    if (!$('ai-dialog').open) $('ai-dialog').showModal();
    refresh(); render();
  }
  ['ai-open-read','ai-open-write'].forEach(id => $(id).addEventListener('click', open));
  $('ai-dialog').addEventListener('close', () => {
    generation++; busy = false; clearTimeout(cameraTimer); releaseScan(scan); scan = null; image = null; releaseImage(); clearProposal();
    // A server-side analysis already sent may still finish; no result will be applied after closing.
    render();
  });
  $('ai-file').addEventListener('change', async () => {
    if (!access || busy) return;
    const file = $('ai-file').files[0]; if (!file) return;
    generation++; releaseScan(scan); scan = null; clearProposal(); releaseImage(); image = null;
    if (file.size > 4*1024*1024 || !['image/jpeg','image/png','image/webp'].includes(file.type)) {
      text('ai-message', msg("Choisissez une image JPEG, PNG ou WebP de moins de 4 Mo.")); render(); return;
    }
    const expected = generation;
    const reader = new FileReader();
    reader.onload = () => {
      if (expected !== generation || !access) return;
      image = {image:reader.result}; imageURL = URL.createObjectURL(file); showImage(imageURL);
      text('ai-message', msg("Photo prête. Vérifiez son cadrage avant l’analyse.")); render();
    };
    reader.onerror = () => { if (expected === generation) text('ai-message', msg("La photo est illisible.")); };
    reader.readAsDataURL(file);
  });
  async function pollCamera(expected) {
    if (expected !== generation || !scan) return;
    try {
      const status = await request('/api/camera/scans/'+encodeURIComponent(scan));
      if (expected !== generation) return;
      if (!status.active) {
        busy = false;
        if (status.state === 'found' && status.preview_ready) {
          image = {scan_id:scan}; showImage('/api/camera/scans/'+encodeURIComponent(scan)+'/preview');
          text('ai-message', msg("Photo prête. Vérifiez son cadrage avant l’analyse."));
        } else text('ai-message', I18n.message(status.message));
        render(); return;
      }
      cameraTimer = setTimeout(() => pollCamera(expected), 350);
    } catch(error) { if (expected === generation) { busy = false; text('ai-message', error.message); render(); } }
  }
  $('ai-camera').addEventListener('click', async () => {
    if (!access || busy) return;
    const expected = ++generation; busy = true; image = null; clearProposal(); releaseImage(); render();
    text('ai-message', msg("Prise de photo…"));
    try {
      const status = await request('/api/assistant/photo', {});
      if (expected !== generation) { releaseScan(status.id); return; }
      scan = status.id; cameraTimer = setTimeout(() => pollCamera(expected), 300);
    } catch(error) { if (expected === generation) { busy = false; text('ai-message', error.message); render(); } }
  });
  function showProposal() {
    const fields = $('ai-proposal-fields'); fields.replaceChildren();
    for (const field of result.fields) {
      const row = document.createElement('div'); row.className = 'ai-field';
      const label = document.createElement('strong'); I18n.text(label, labels[field.field] || field.field);
      const value = document.createElement('span'); value.textContent = String(field.value);
      const origin = document.createElement(field.origin === 'web' ? 'a' : 'small');
      I18n.text(origin, field.origin === 'web' ? msg("Source Web") : msg("Étiquette"));
      if (field.origin === 'web') { origin.href = field.source_url; origin.target = '_blank'; origin.rel = 'noopener noreferrer'; }
      const evidence = document.createElement('small'); evidence.textContent = field.evidence;
      row.append(label,value,origin,evidence); fields.append(row);
    }
    $('ai-proposal-title').textContent = result.title;
    $('ai-visible-text').textContent = result.visible_text;
    $('ai-warnings').textContent = result.warnings.map(value=>I18n.message(value)).join('\n');
    $('ai-warnings').hidden = !result.warnings.length;
    const sources = $('ai-sources'); sources.replaceChildren();
    for (const source of result.sources) {
      const link = document.createElement('a'); link.href = source.url; link.textContent = source.title;
      link.target = '_blank'; link.rel = 'noopener noreferrer'; sources.append(link,document.createElement('br'));
    }
    if (!result.sources.length) I18n.text(sources, msg("Aucune source Web utilisée. Seules les informations de l’étiquette sont proposées."));
    $('ai-proposal').hidden = false;
  }
  $('ai-analyse').addEventListener('click', async () => {
    if (!access || busy || !image) return;
    const expected = generation; busy = true; clearProposal(); render();
    text('ai-message', msg("Analyse de l’étiquette et recherche des informations…"));
    try {
      const data = await request('/api/assistant/analyse', {...image,language:I18n.getLanguage()});
      if (expected !== generation || !access) return;
      result = data; showProposal();
      text('ai-message', Object.keys(data.main).length ? msg("Proposition prête. Vérifiez les valeurs et leurs sources.") : msg("Aucune information suffisamment fiable n’a été trouvée. Essayez une photo plus nette."));
    } catch(error) { if (expected === generation) text('ai-message', error.message); }
    finally { busy = false; render(); }
  });
  $('ai-apply').addEventListener('click', () => {
    if (!access || busy || !result || !Object.keys(result.main).length) return;
    document.dispatchEvent(new CustomEvent('opt-station-ai-apply', {detail:{main:result.main}}));
    $('ai-dialog').close();
  });
  document.addEventListener('opt-station-status', event => {
    access = event.detail.access; available = Boolean(event.detail.camera?.available);
    if (!access) { configuration = null; $('ai-key').value = ''; if ($('ai-dialog').open) $('ai-dialog').close(); }
    else if (!dirty && !saving && configuration?.revision !== event.detail.assistant?.revision) refresh();
    render();
  });
  document.addEventListener('opt-station-tab', event => { if (event.detail.tab === 'configuration' && !dirty) refresh(); });
  document.addEventListener('opt-station-language', () => { render(); if (result) showProposal(); });
  render();
})();
