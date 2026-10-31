"use strict";
(() => {
  const I18n = window.OPT_I18N;
  I18n.init();
  const $ = (id) => document.getElementById(id);
  let configuration = null, pending = false;
  const text = (id, value) => { if ($(id)) I18n.text($(id), value); };
  function render() {
    if (!configuration) return;
    text("https-state", I18n.msg(!configuration.enabled ? "Non installé" : configuration.secure ? "HTTPS actif" : "Connexion HTTP"));
    text("https-message", I18n.msg(!configuration.enabled
      ? "HTTPS n’est pas installé sur cette station. Suivez le guide d’installation HTTPS."
      : configuration.secure
        ? "Cette connexion est chiffrée. Pour un autre appareil, installez une fois le certificat de cette station."
        : "Installez le certificat de cette station sur cet appareil, puis ouvrez son adresse HTTPS."));
    const address = $("https-address");
    if (address) {
      address.hidden = !configuration.url;
      address.href = configuration.url || "#";
      address.textContent = configuration.url || "";
    }
    $("https-certificate").hidden = !configuration.certificate_available;
    const certificateName = $("https-certificate-name");
    if (certificateName) certificateName.textContent = configuration.certificate_name || I18n.msg("Certificat indisponible.");
    text("https-fingerprint", configuration.fingerprint_sha256 || I18n.msg("Certificat indisponible."));
    const aliases = $("https-aliases");
    if (aliases) {
      aliases.replaceChildren();
      for (const url of configuration.aliases) {
        const link = document.createElement("a");
        link.href = url; link.textContent = url; aliases.append(link, document.createElement("br"));
      }
    }
  }
  async function refresh() {
    if (pending) return;
    pending = true;
    try {
      const response = await fetch("/api/configuration/https", {cache: "no-store", signal: AbortSignal.timeout(10000)});
      if (!response.ok) throw new Error();
      configuration = await response.json(); render();
    } catch { text("https-message", I18n.msg("La station est injoignable.")); }
    finally { pending = false; }
  }
  document.addEventListener("opt-station-language", render);
  document.addEventListener("opt-station-tab", (event) => { if (event.detail.tab === "configuration") refresh(); });
  refresh();
})();
