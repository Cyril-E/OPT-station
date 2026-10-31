"use strict";

// Move within settings without reloading forms or changing their access rights.
(() => {
  const panel = document.getElementById("panel-configuration");
  const contents = document.getElementById("configuration-contents");
  if (!panel || !contents) return;
  const wide = window.matchMedia("(min-width: 1450px)");
  const adapt = () => { contents.open = wide.matches; };
  adapt();
  wide.addEventListener("change", adapt);

  contents.addEventListener("click", (event) => {
    const link = event.target.closest("a[href^='#configuration-']");
    if (!link || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const section = document.getElementById(link.hash.slice(1));
    if (!section || !panel.contains(section)) return;
    event.preventDefault();
    if (!wide.matches) contents.open = false;
    contents.querySelectorAll("a").forEach((item) => item.removeAttribute("aria-current"));
    link.setAttribute("aria-current", "location");
    requestAnimationFrame(() => {
      section.querySelector("h2").focus({preventScroll: true});
      section.scrollIntoView({block: "start", behavior: "instant"});
    });
  });
})();
