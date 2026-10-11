// Overview: the app mode, what is live, what is in the draft, and the API the app calls.
import { fill, h, icon } from "../dom.js";
import { changes, servedServices, state, text } from "../state.js";
import { chooseMode } from "./packs.js";

export const title = "Overview";

export function render(root) {
  const { catalog, release } = state.draft;
  const services = catalog.services;
  // What the app gets: services in packs it doesn't get don't count.
  const enabled = servedServices(catalog).length;
  const packs = catalog.packs || [];
  const maintenance = services.filter((s) => s.maintenance).length;
  const published = state.published || {};
  const pending = changes();
  const stat = (label, value, hint) => h("div", { class: "card stat" }, h("div", { class: "muted small", text: label }), h("div", { class: "value", text: value }), hint && h("div", { class: "hint", text: hint }));
  const origin = location.origin;
  fill(root, 
    h("div", { class: "page-head" }, h("div", { class: "grow" }, h("h1", { text: "Overview" }), h("div", { class: "muted", text: "Manage what the Anar app shows, then publish." }))),
    // First: the switch to reach for when international internet is cut.
    (state.live.catalog.packs || []).length > 0 && h("div", { class: "stack", style: { marginBottom: "20px" } }, modeCard()),
    h("div", { class: "stats" },
      stat("Services", `${enabled} / ${services.length}`, packs.length ? "in the app / total" : "enabled / total"),
      stat("Categories", String(catalog.categories.length)),
      stat("Under maintenance", String(maintenance)),
      stat("Minimum version", String(release.default.minimumSupportedVersion), `latest ${release.default.latestVersion ?? release.default.minimumSupportedVersion}`)),
    h("div", { class: "stack" },
      h("section", { class: "card" },
        h("div", { class: "card-head" }, h("h2", { class: "grow", text: "Live version" }), h("span", { class: "chip success", text: "Live" })),
        h("div", { class: "card-body" },
          published.publishedAt
            ? [h("div", {}, `Published ${new Date(published.publishedAt * 1000).toLocaleString()} by `, h("strong", { text: published.publishedBy })), published.note && h("div", { class: "muted", text: published.note })]
            : h("div", { class: "muted", text: "Not published from the dashboard yet." }),
          h("div", { class: "muted small ltr", style: { marginTop: "8px" }, text: `configVersion ${state.live.catalog.configVersion || "—"}` }))),
      h("section", { class: "card" },
        h("div", { class: "card-head" }, h("h2", { class: "grow", text: "Draft" }), h("span", { class: `chip ${pending.length ? "warning" : ""}`, text: pending.length ? `${pending.length} unpublished change${pending.length === 1 ? "" : "s"}` : "Same as live" })),
        h("div", { class: "card-body" }, pending.length
          ? h("ul", { class: "changes" }, pending.slice(0, 12).map((c) => h("li", { text: c })), pending.length > 12 && h("li", { class: "muted", text: `and ${pending.length - 12} more…` }))
          : h("div", { class: "muted", text: "Edit services, categories, releases or settings: changes collect here until you publish." }))),
      h("section", { class: "card" },
        h("div", { class: "card-head" }, h("h2", { class: "grow", text: "API" })),
        h("div", { class: "card-body stack", style: { gap: "8px" } },
          [["Catalog", "/api/v1/config?platform=android&channel=bazaar&appVersion=1"], ["Update policy", "/api/v1/app/version?platform=android&channel=bazaar&appVersion=1"]].map(([label, path]) =>
            h("div", { class: "row" }, h("span", { class: "muted", style: { width: "110px" }, text: label }), h("a", { class: "mono ltr", href: path, target: "_blank", rel: "noopener", style: { minWidth: 0, overflowWrap: "anywhere" }, text: `${origin}${path}` }), icon("external")))))));
}

/**
 * What users get, switched right away: the current catalog, the catalog with one published
 * pack, or a pack alone when it replaces the catalog.
 */
function modeCard() {
  const live = state.live.catalog;
  const packs = live.packs || [];
  const on = packs.filter((p) => p.active);
  // null: the current catalog; undefined: several packs on (switched on the Packs page).
  const current = on.length === 0 ? null : on.length === 1 ? on[0].id : undefined;
  const count = (id) => servedServices({ ...live, packs: packs.map((p) => ({ ...p, active: p.id === id })) }).length;
  const option = (pack) => {
    const id = pack ? pack.id : null;
    return h("button", { class: "btn", "aria-pressed": String(current === id), on: { click: () => { if (current !== id) chooseMode(pack); } } },
      h("span", { dir: "auto", text: pack ? text(pack.title, pack.id) : "Current catalog" }),
      h("span", { class: "muted small", text: `${count(id)} services${pack?.exclusive ? " · on its own" : ""}` }));
  };
  const label = current === null ? "Current catalog" : on.map((p) => text(p.title, p.id)).join(" + ");
  return h("section", { class: "card" },
    h("div", { class: "card-head" }, h("h2", { class: "grow", text: "App mode" }),
      h("span", { class: `chip ${current === null ? "success" : "warning"}`, dir: "auto", text: label })),
    h("div", { class: "card-body stack", style: { gap: "10px" } },
      h("div", { class: "seg modes", role: "group", "aria-label": "App mode" }, option(null), packs.map(option)),
      h("div", { class: "hint", text: "Switching is live right away: users get it the next time the app opens or refreshes its catalog. Only the mode is published; other draft changes stay unpublished." })));
}
