"use strict";

(() => {
  const I18n = window.OPT_I18N;
  I18n.init();
  const msg = I18n.msg;
  const $ = (id) => document.getElementById(id);
  let access = false, tab = "read", configuration = null, loading = false, pendingPower = false, copying = false;
  const text = (id, value) => { I18n.text($(id), I18n.message(value)); };
  function render() {
    text("mcp-state", !configuration ? msg("À vérifier") : configuration.enabled ? msg("Activé") : msg("Désactivé"));
    $("mcp-state").classList.toggle("in-stock", Boolean(configuration?.enabled));
    $("mcp-toggle").disabled = !access || !configuration || loading || pendingPower;
    $("mcp-reload").disabled = loading;
    text("mcp-toggle", configuration?.enabled ? msg("Désactiver le serveur MCP") : msg("Activer le serveur MCP"));
    const endpoint = configuration?.endpoint || "";
    if ($("mcp-endpoint").value !== endpoint) $("mcp-endpoint").value = endpoint;
    if ($("mcp-copy")) $("mcp-copy").disabled = copying || !endpoint;
    text("mcp-access", !access ? msg("Le réglage MCP nécessite l’accès local ou complet. Les informations restent consultables ici.")
      : configuration?.enabled ? msg("Le MCP est activé. Ajoutez cette adresse dans votre client IA compatible, depuis le même réseau que le Pi.")
      : msg("Le MCP est désactivé. Activez-le pour autoriser les IA de votre réseau à consulter et modifier les fiches de bobines, et gérer les favoris et modèles."));
  }
  async function request(body) {
    const response = await fetch("/api/configuration/mcp", {method: body ? "PUT" : "GET", cache: "no-store", credentials: "same-origin",
      signal: AbortSignal.timeout(10000), ...(body ? {headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)} : {})});
    const result = await response.json();
    if (!response.ok) throw new Error(I18n.message(result.detail || msg("Réglage MCP indisponible.")));
    return I18n.messages(result);
  }
  async function refresh() {
    if (loading) return;
    loading = true; render();
    try { configuration = await request(); }
    catch (error) { text("mcp-result", error.message || msg("La station est injoignable.")); }
    finally { loading = false; render(); }
  }
  async function copyEndpoint() {
    const endpoint = configuration?.endpoint;
    if (!endpoint || copying) return;
    const previousFocus = document.activeElement;
    const input = $("mcp-endpoint");
    const selection = [input.selectionStart, input.selectionEnd];
    let copied = false;
    copying = true; render();
    try {
      if (window.isSecureContext && navigator.clipboard?.writeText) {
        try { await navigator.clipboard.writeText(endpoint); copied = true; }
        catch { /* The selected input also supports browsers denying clipboard access. */ }
      }
      if (!copied) {
        // LAN HTTP has no Clipboard API. Keep this synchronous in the click event.
        input.focus({preventScroll: true}); input.select();
        const setClipboard = (event) => {
          if (!event.clipboardData) return;
          event.clipboardData.setData("text/plain", endpoint);
          event.preventDefault();
        };
        document.addEventListener("copy", setClipboard);
        try { copied = document.execCommand("copy"); }
        finally { document.removeEventListener("copy", setClipboard); }
      }
      if (!copied) throw new Error("copy unavailable");
      text("mcp-result", msg("Adresse MCP copiée."));
    } catch {
      input.focus({preventScroll: true}); input.select();
      text("mcp-result", msg("Copie automatique indisponible. L’adresse est sélectionnée : copiez-la avec Ctrl+C ou ⌘C."));
    } finally {
      copying = false; render();
      if (copied) {
        input.setSelectionRange(...selection);
        previousFocus?.focus({preventScroll: true});
      }
    }
  }
  $("mcp-copy")?.addEventListener("click", copyEndpoint);
  $("mcp-toggle").addEventListener("click", async () => {
    if (!configuration || loading || !access || pendingPower) return;
    loading = true; render();
    try {
      configuration = await request({enabled: !configuration.enabled, revision: configuration.revision});
      text("mcp-result", configuration.enabled ? msg("MCP activé et choix enregistré sur le Pi.") : msg("MCP désactivé et choix enregistré sur le Pi."));
    } catch (error) { text("mcp-result", error.message || msg("La station est injoignable. Vérifiez le réglage avant de réessayer.")); }
    finally { loading = false; render(); }
  });
  $("mcp-info").addEventListener("click", () => $("mcp-dialog").showModal());
  $("mcp-reload").addEventListener("click", refresh);
  document.addEventListener("opt-station-tab", (event) => { tab = event.detail.tab; if (tab === "configuration") refresh(); });
  document.addEventListener("opt-station-status", (event) => {
    access = event.detail.access; pendingPower = Boolean(event.detail.power?.pending);
    if (tab === "configuration" && event.detail.mcp?.revision !== configuration?.revision) refresh();
    render();
  });
  document.addEventListener("opt-station-language", render);
})();
