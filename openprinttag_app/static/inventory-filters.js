"use strict";
(() => {
  const key = value => String(value ?? "").trim().toLocaleLowerCase("fr");
  function values(items, field) {
    const unique = new Map();
    for (const item of items) {
      const value = String(item.main?.[field] ?? "").trim();
      if (!unique.has(key(value))) unique.set(key(value), value);
    }
    return [...unique].sort((a, b) => a[1].localeCompare(b[1], "fr"));
  }
  function matches(item, view, brands, materials) {
    if (!item.in_stock && !item.completed_at) return false;
    if (view === "completed" && !item.completed_at) return false;
    if (view === "stock" && (!item.in_stock || item.completed_at || item.usage_state !== "stock")) return false;
    if (view === "production" && (!item.in_stock || item.completed_at || item.usage_state !== "in_service")) return false;
    return (!brands.size || brands.has(key(item.main?.brand_name))) &&
      (!materials.size || materials.has(key(item.main?.material_type)));
  }
  window.OPT_INVENTORY_FILTERS = {values, matches};
})();
