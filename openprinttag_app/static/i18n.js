"use strict";

// Only explicitly marked UI messages are translated. User data and form values
// remain verbatim; changing language never rebuilds or reloads a form.
(() => {
  const EN = window.OPT_EN || {};
  const catalogs = {fr: {}, en: EN, es: window.OPT_ES || {}, de: window.OPT_DE || {}};
  const locales = {fr: "fr-FR", en: "en-GB", es: "es-ES", de: "de-DE"};
  const supported = (value) => Object.hasOwn(catalogs, value) ? value : "fr";
  let language = "fr", connected = false;
  try { language = supported(window.localStorage.getItem("opt-station-language")); } catch { /* Per-page choice still works. */ }
  const staticText = [], staticAttributes = [];
  const reverse = new Map(Object.values(catalogs).flatMap((catalog) => Object.entries(catalog).map(([fr, target]) => [target, fr])));
  const escape = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const patterns = [];
  for (const fr of Object.keys(EN)) {
    if (!/\{\d+\}/.test(fr)) continue;
    for (const candidate of new Set([fr, ...Object.values(catalogs).map((catalog) => catalog[fr]).filter(Boolean)])) {
      const order = [];
      const pieces = candidate.split(/(\{\d+\})/g).map((part) => {
        if (/^\{\d+\}$/.test(part)) { order.push(Number(part.slice(1,-1))); return "([\\s\\S]*?)"; }
        return escape(part);
      });
      patterns.push({expression: new RegExp("^" + pieces.join("") + "$"), source: fr, order});
    }
  }
  const germanPlural = (source) => source === "Depuis {0} jour{1}" ? "en" : /bobine\{1\}/.test(source) ? "n" : "";
  function translate(source, args = []) {
    const catalog = catalogs[language];
    const template = Object.hasOwn(catalog, source) ? catalog[source] : source;
    return template.replace(/\{(\d+)\}/g, (match, index) => {
      if (Number(index) >= args.length) return match;
      // These existing French/English templates pass a plural suffix as {1}.
      // German uses Spulen and (seit) Tagen; all other arguments stay verbatim.
      if (language === "de" && Number(index) === 1 && germanPlural(source) && args[index]) return germanPlural(source);
      return String(args[index] ?? "");
    });
  }
  class Message {
    constructor(source, args) { this.source = source; this.args = args; }
    toString() { return translate(this.source, this.args); }
    toJSON() { return this.toString(); }
  }
  const msg = (source, ...args) => new Message(source, args);
  function message(value) {
    if (value instanceof Message) return value;
    const text = String(value ?? "");
    if (Object.hasOwn(EN, text)) return msg(text);
    if (reverse.has(text)) return msg(reverse.get(text));
    for (const pattern of patterns) {
      const match = text.match(pattern.expression);
      if (!match) continue;
      const args = [];
      pattern.order.forEach((index, position) => {
        const value = match[position + 1];
        if (index === 1 && germanPlural(pattern.source)) args[index] = value ? "s" : "";
        else args[index] = pattern.source === "{0} doit être un nombre{1}." && index === 1 && (value === " entier" || reverse.get(value) === " entier") ? msg(" entier") : value;
      });
      return new Message(pattern.source, args);
    }
    // Some validation messages append a list of canonical field names.
    for (const source of Object.keys(EN)) {
      if (source.endsWith(":")) {
        if (text.startsWith(source + " ")) return msg("{0}{1}", msg(source), text.slice(source.length));
        for (const catalog of Object.values(catalogs)) {
          const target = catalog[source];
          if (target && text.startsWith(target + " ")) return msg("{0}{1}", msg(source), text.slice(target.length));
        }
      }
    }
    return msg(text);
  }
  function messages(value) {
    if (!value || typeof value !== "object" || value instanceof Message) return value;
    if (Array.isArray(value)) return value.map(messages);
    const result = {...value};
    for (const [key, child] of Object.entries(result)) {
      if (["main", "aux"].includes(key)) continue;
      if (["message", "detection_message", "detail"].includes(key) && typeof child === "string" && child) result[key] = message(child);
      else if (key === "warnings" && Array.isArray(child)) result[key] = child.map((item) => typeof item === "string" ? message(item) : item);
      else if (child && typeof child === "object") result[key] = messages(child);
    }
    return result;
  }
  function text(element, value) {
    if (value instanceof Message) {
      element.dataset.msg = "true"; element.optMessage = value;
    } else {
      delete element.dataset.msg; delete element.optMessage; delete element.optMessageNode;
      element.dataset.l10nRaw = "true";
    }
    element.textContent = String(value ?? "");
    if (value instanceof Message) element.optMessageNode = element.firstChild;
  }
  function attribute(element, name, value) {
    if (value instanceof Message) {
      element.dataset.msgAttrs = "true";
      (element.optAttributes ||= {})[name] = value;
    } else if (element.optAttributes) delete element.optAttributes[name];
    element.setAttribute(name, String(value ?? ""));
  }
  function refresh() {
    document.documentElement.lang = language;
    for (const [node, source] of staticText) if (node.isConnected) node.textContent = source.replace(source.trim(), translate(source.trim()));
    for (const [element, name, source] of staticAttributes) if (element.isConnected) element.setAttribute(name, translate(source));
    document.querySelectorAll("[data-msg]").forEach((element) => {
      // A translated label may also own an input, unit or required marker.
      // Update its original text node, never replace those children.
      if (element.optMessage && element.optMessageNode?.parentNode === element) {
        element.optMessageNode.textContent = String(element.optMessage);
      }
    });
    document.querySelectorAll("[data-msg-attrs]").forEach((element) => {
      for (const [name, value] of Object.entries(element.optAttributes || {})) element.setAttribute(name, String(value));
    });
    const select = document.getElementById("language-select");
    if (select) select.value = language;
  }
  function apply(value, save = false) {
    language = supported(value);
    if (save) {
      try { window.localStorage.setItem("opt-station-language", language); }
      catch { const note = document.getElementById("language-storage-note"); if (note) note.hidden = false; }
    }
    refresh();
    document.dispatchEvent(new CustomEvent("opt-station-language", {detail: {language}}));
  }
  function init() {
    if (connected || !document.getElementById("language-select")) return;
    connected = true;
    document.querySelectorAll("[data-i18n]").forEach((element) => {
      if (element.dataset.l10nRaw || element.optMessage) return;
      for (const child of element.childNodes) if (child.nodeType === 3 && child.textContent.trim()) staticText.push([child, child.textContent]);
    });
    document.querySelectorAll("[data-i18n-attrs]").forEach((element) => {
      for (const name of element.dataset.i18nAttrs.split(" ")) if (element.hasAttribute(name)) staticAttributes.push([element, name, element.getAttribute(name)]);
    });
    document.getElementById("language-select").addEventListener("change", (event) => apply(event.target.value, true));
    refresh();
  }
  window.OPT_I18N = {msg, message, messages, text, attribute, init, refresh, translate, getLanguage: () => language,
    locale: () => locales[language], setLanguage: (value) => apply(value, true)};
  document.documentElement.lang = language;
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, {once: true}); else init();
  window.addEventListener("storage", (event) => { if (event.key === "opt-station-language") apply(event.newValue); });
})();
