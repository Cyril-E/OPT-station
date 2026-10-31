"use strict";

// Independent of API loading and NFC permissions; apply before the stylesheet.
(() => {
  const I18n = window.OPT_I18N;
  I18n.init();
  const msg = I18n.msg;
  let theme = "dark";
  try {
    const saved = window.localStorage.getItem("opt-station-theme");
    if (["dark", "light"].includes(saved)) theme = saved;
  } catch { /* Private browsing can prevent preference storage. */ }
  function apply(value, save = false) {
    theme = value === "light" ? "light" : "dark";
    document.documentElement.dataset.theme = theme;
    document.querySelector('meta[name="theme-color"]').content = theme === "dark" ? "#17181a" : "#145b48";
    const select = document.getElementById("theme-select"), toggle = document.getElementById("theme-toggle");
    if (select) select.value = theme;
    if (toggle) {
      const label = theme === "dark" ? msg("Passer au thème clair") : msg("Passer au thème sombre");
      I18n.text(toggle, theme === "dark" ? "☀" : "☾");
      I18n.attribute(toggle, "title", label);
      I18n.attribute(toggle, "aria-label", label);
    }
    if (save) {
      try { window.localStorage.setItem("opt-station-theme", theme); }
      catch {
        const note = document.getElementById("theme-storage-note");
        if (note) note.hidden = false;
      }
    }
  }
  function connectControls() {
    apply(theme);
    document.getElementById("theme-toggle")?.addEventListener("click", () => apply(theme === "dark" ? "light" : "dark", true));
    document.getElementById("theme-select")?.addEventListener("change", (event) => apply(event.target.value, true));
  }
  apply(theme);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", connectControls, {once: true});
  else connectControls();
  window.addEventListener("storage", (event) => {
    if (event.key === "opt-station-theme") apply(event.newValue);
  });
  document.addEventListener("opt-station-language", () => apply(theme));
})();
