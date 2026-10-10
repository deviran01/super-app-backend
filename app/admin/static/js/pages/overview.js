// Overview: the app mode, what is live, what is in the draft, and the API the app calls.
import { fill, h, icon } from "../dom.js";
import { changes, packActive, state, text } from "../state.js";
import { switchLive } from "./packs.js";

export const title = "Overview";

export function render(root) {
  const { catalog, release } = state.draft;
  const services = catalog.services;
  // What the app gets: services in switched-off packs don't count.
  const enabled = services.filter((s) => s.enabled !== false && (!s.pack || packActive(s.pack))).length;
  const packs = catalog.packs || [];
  const maintenance = services.filter((s) => s.maintenance).length;
  const published = state.published || {};
  const pending = changes();
  const stat = (label, value, hint) => h("div", { class: "card stat" }, h("div", { class: "muted small", text: label }), h("div", { class: "value", text: value }), hint && h("div", { class: "hint", text: hint }));
  const origin = location.origin;
  fill(root, 
    h("div", { class: "page-head" }, h("div", { class: "grow" }, h("h1", { text: "Overview" }), h("div", { class: "muted", text: "Manage what the Anar app shows, then publish." }))),
    // First: the switch to reach for when international internet is cut.
    (state.live.catalog.packs || []).length > 0 && h("div", { class: "stack", style: { marginBottom: "20px" } }, state.live.catalog.packs.map(modeCard)),
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

/** The current catalog, or with a published pack: what users get, switched right away. */
function modeCard(pack) {
  const live = state.live.catalog;
  const otherPacksOn = new Set((live.packs || []).filter((p) => p.active && p.id !== pack.id).map((p) => p.id));
  const base = live.services.filter((s) => s.enabled !== false && (!s.pack || otherPacksOn.has(s.pack))).length;
  const extra = live.services.filter((s) => s.enabled !== false && s.pack === pack.id).length;
  const on = Boolean(pack.active);
  const option = (active, label, count) => h("button", { class: "btn", "aria-pressed": String(on === active),
    on: { click: () => { if (on !== active) switchLive(pack, active); } } },
    h("span", { dir: "auto", text: label }), h("span", { class: "muted small", text: `${count} services` }));
  return h("section", { class: "card" },
    h("div", { class: "card-head" }, h("h2", { class: "grow", text: "App mode" }),
      h("span", { class: `chip ${on ? "warning" : "success"}`, dir: "auto", text: on ? text(pack.title, pack.id) : "Current catalog" })),
    h("div", { class: "card-body stack", style: { gap: "10px" } },
      h("div", { class: "seg modes", role: "group", "aria-label": "App mode" },
        option(false, "Current catalog", base),
        option(true, text(pack.title, pack.id), base + extra)),
      h("div", { class: "hint", text: "Switching is live right away: users get it the next time the app opens or refreshes its catalog. Only the mode is published; other draft changes stay unpublished." })));
}
