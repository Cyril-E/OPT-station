"use strict";

(() => {
  const I18n = window.OPT_I18N;
  I18n.init();
  const msg = I18n.msg;
  const $ = (id) => document.getElementById(id);
  const text = (id, value) => { I18n.text($(id), I18n.message(value)); };
  let access = false, tab = "read", capabilities = null, loading = false, prepared = null;
  let latest = null, waitingInstance = null, waitingAction = null, uncertain = false, expiry = null, dismissedFailure = null;
  const failureKey = () => `${latest?.instance_id}:${latest?.action}:${latest?.message?.source || latest?.message}`;

  async function request(path, body) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 25000);
    try {
      const response = await fetch(path, {method: body ? "POST" : "GET", credentials: "same-origin", cache: "no-store",
        signal: controller.signal, ...(body ? {headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)} : {})});
      const result = await response.json();
      if (!response.ok) {
        const error = new Error(I18n.message(result.detail || msg("La demande n’a pas été acceptée.")));
        error.status = response.status;
        throw error;
      }
      return I18n.messages(result);
    } finally { clearTimeout(timer); }
  }

  function render() {
    const pending = Boolean(latest?.pending) || uncertain;
    $("power-off").disabled = loading || pending || !access || !capabilities?.actions?.poweroff;
    $("power-reboot").disabled = loading || pending || !access || !capabilities?.actions?.reboot;
    $("power-refresh").disabled = loading || pending || !access;
    text("power-message", !access ? msg("Activez l’accès complet dans Paramètres → Accès distant pour arrêter ou redémarrer le Pi.")
      : pending ? msg("Demande en cours. Aucune nouvelle opération ne sera lancée.")
      : loading ? msg("Vérification des droits système…") : latest?.phase === "failed" ? latest.message
      : capabilities?.message || msg("Vérifiez les droits pour rendre les commandes disponibles."));
    document.querySelector(".app-shell").inert = pending;
    document.body.classList.toggle("power-pending", pending);
    $("power-banner").hidden = !pending && (latest?.phase !== "failed" || dismissedFailure === failureKey());
    $("power-dismiss").hidden = pending;
    if (pending) {
      document.querySelectorAll("dialog[open]").forEach((dialog) => dialog.close());
      text("power-banner-title", (latest?.action || waitingAction) === "reboot" ? msg("Redémarrage du Pi") : msg("Arrêt du Pi"));
      text("power-banner-message", uncertain
        ? msg("La réponse du Pi n’a pas pu être vérifiée. Contrôlez son état avant toute nouvelle action. La demande n’est pas renvoyée.")
        : latest?.message || msg("Demande envoyée au système. Patientez…"));
    } else if (latest?.phase === "failed") {
      text("power-banner-title", msg("La demande a été refusée"));
      text("power-banner-message", latest.message);
    }
  }

  async function refresh() {
    if (!access || loading || latest?.pending || uncertain) { render(); return; }
    loading = true; render();
    try {
      capabilities = await request("/api/system/power");
      receive(capabilities);
    } catch (error) {
      capabilities = {actions: {}, message: error.status === 403 ? msg("L’accès complet a été fermé. Actualisez la page.")
        : msg("Impossible de vérifier les droits du Pi. Réessayez avec « Vérifier les droits ».")};
    } finally { loading = false; render(); }
  }

  function receive(power) {
    if (!power) return;
    if (waitingInstance && power.instance_id !== waitingInstance) {
      // A new server instance acknowledges the return; never resend a power command.
      window.location.reload();
      return;
    }
    latest = power;
    if (power.pending) {
      waitingInstance = power.instance_id; waitingAction = power.action; uncertain = false;
    } else if (power.phase === "failed") {
      waitingInstance = null; uncertain = false;
    }
    render();
  }

  async function prepare(action) {
    if (loading || latest?.pending || uncertain) return;
    loading = true; render();
    try {
      prepared = await request("/api/system/power/prepare", {action});
      if (latest?.phase === "failed") latest = {...latest, phase: "idle", message: ""};
      const shutdown = action === "poweroff";
      text("power-dialog-title", shutdown ? msg("Arrêter le Raspberry Pi ?") : msg("Redémarrer le Raspberry Pi ?"));
      text("power-dialog-description", shutdown
        ? msg("OPT Station et ses accès réseau vont s’arrêter. Enregistrez les formulaires ouverts sur vos autres écrans. Attendez l’arrêt complet du Pi avant de couper son alimentation. Pour retrouver la station, il faudra le rallumer sur place.")
        : msg("OPT Station et ses accès réseau seront interrompus pendant le redémarrage. Enregistrez les formulaires ouverts sur vos autres écrans. L’interface reviendra automatiquement lorsque le Pi sera disponible."));
      text("power-confirm", shutdown ? msg("Oui, arrêter le Pi") : msg("Oui, redémarrer le Pi"));
      text("power-dialog-result", "");
      $("power-confirm").disabled = false;
      $("power-dialog").showModal();
      $("power-cancel").focus();
      expiry = setTimeout(() => {
        prepared = null; $("power-confirm").disabled = true;
        text("power-dialog-result", msg("Cette confirmation a expiré. Annulez puis reprenez le bouton."));
      }, prepared.expires_in_seconds * 1000);
    } catch (error) {
      capabilities = {...capabilities, message: error.status ? error.message : msg("La station est injoignable. Aucune commande système n’a été envoyée.")};
    } finally { loading = false; render(); }
  }

  async function confirm() {
    if (!prepared || loading) return;
    const body = {action: prepared.action, confirmation_token: prepared.confirmation_token};
    dismissedFailure = null;
    prepared = null; loading = true;
    waitingInstance = latest?.instance_id || null; waitingAction = body.action;
    uncertain = true;
    render();
    text("power-banner-message", msg("Transmission de la demande au Pi…"));
    try {
      receive(await request("/api/system/power", body));
    } catch (error) {
      if (error.status) {
        uncertain = false; waitingInstance = null;
        latest = {...latest, pending: false, phase: "failed", message: error.message};
      } // A lost response is ambiguous. Poll reads only; never retry this POST.
    } finally { loading = false; render(); }
  }

  $("power-off").addEventListener("click", () => prepare("poweroff"));
  $("power-reboot").addEventListener("click", () => prepare("reboot"));
  $("power-refresh").addEventListener("click", refresh);
  $("power-confirm").addEventListener("click", confirm);
  $("power-dialog").addEventListener("close", () => { clearTimeout(expiry); prepared = null; });
  $("power-dismiss").addEventListener("click", () => { dismissedFailure = failureKey(); render(); });
  document.addEventListener("opt-station-tab", (event) => {
    tab = event.detail.tab;
    if (tab === "configuration") refresh();
  });
  document.addEventListener("opt-station-status", (event) => {
    const gainedAccess = !access && event.detail.access;
    access = event.detail.access;
    receive(event.detail.power);
    if (tab === "configuration" && gainedAccess) refresh();
    if (!access && $("power-dialog").open) $("power-dialog").close();
    render();
  });
  document.addEventListener("opt-station-offline", () => {
    if (!latest?.pending && !uncertain) return;
    text("power-banner-message", (latest?.action || waitingAction) === "reboot"
      ? msg("Connexion interrompue. L’interface se rechargera au retour du Pi. Si l’attente se prolonge, vérifiez son écran.")
      : msg("La station ne répond plus. Attendez l’arrêt complet du Pi avant de couper son alimentation; l’absence de connexion seule ne confirme pas cet arrêt."));
  });
  document.addEventListener("opt-station-language", render);
})();
