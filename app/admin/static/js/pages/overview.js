// Overview: what is live, what is in the draft, and the API the app calls.
import { fill, h, icon } from "../dom.js";
import { changes, state } from "../state.js";

export const title = "Overview";

export function render(root) {
  const { catalog, release } = state.draft;
  const services = catalog.services;
  const enabled = services.filter((s) => s.enabled !== false).length;
  const maintenance = services.filter((s) => s.maintenance).length;
  const published = state.published || {};
  const pending = changes();
  const stat = (label, value, hint) => h("div", { class: "card stat" }, h("div", { class: "muted small", text: label }), h("div", { class: "value", text: value }), hint && h("div", { class: "hint", text: hint }));
  const origin = location.origin;
  fill(root, 
    h("div", { class: "page-head" }, h("div", { class: "grow" }, h("h1", { text: "Overview" }), h("div", { class: "muted", text: "Manage what the Anar app shows, then publish." }))),
    h("div", { class: "stats" },
      stat("Services", `${enabled} / ${services.length}`, "enabled / total"),
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
            h("div", { class: "row" }, h("span", { class: "muted", style: { width: "110px" }, text: label }), h("a", { class: "mono ltr", href: path, target: "_blank", rel: "noopener", text: `${origin}${path}` }), icon("external")))))));
}
