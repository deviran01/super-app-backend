// Statistics: API traffic counted by the server, and anonymous daily totals reported by the
// app (no identifiers: see app/stats.py). Loads its own data; the draft doesn't affect it.
import { api } from "../api.js";
import { fill, h, icon } from "../dom.js";
import { state, text } from "../state.js";
import { showError } from "../ui.js";
import { logo } from "./services.js";

export const title = "Statistics";

const RANGES = [[7, "7 days"], [30, "30 days"], [90, "90 days"]];
const CHANNELS = [["", "All stores"], ["bazaar", "Cafe Bazaar"], ["myket", "Myket"], ["direct", "Direct"], ["other", "Other"]];
const METRICS = [
  ["activeUsers", "Active users"],
  ["apiCalls", "API calls"],
  ["appOpens", "App opens"],
  ["serviceOpens", "Service opens"],
  ["installs", "New installs"],
];
const SOURCES = { home: "Home", favorites: "Favorites", recent: "Recent", category: "Category page", search: "Search", tabs: "Open tabs", quick_switch: "Quick switch", add_service: "Add service" };
const ERRORS = {
  offline: "Device offline", host_not_found: "Host not found", timeout: "Timed out", connection_failed: "Connection failed",
  insecure_connection: "Certificate error", unsupported_url: "Unsupported link", crashed: "Page crashed",
  web_view_unavailable: "WebView unavailable", generic: "Other error",
};
const ENDPOINTS = { config: "Catalog", version: "Update policy", events: "Usage reports" };
const STATUSES = { "2xx": "OK", "304": "Not modified", "4xx": "Rejected", "5xx": "Server error" };
const SCOPES = { cache: "Cache only", service: "One service", all: "Everything" };

const view = { days: 30, channel: "", metric: "activeUsers" };
const number = new Intl.NumberFormat("en");
const fmt = (n) => number.format(n || 0);
const pct = (part, whole) => (whole ? `${Math.round((part / whole) * 100)}%` : "—");

let latest = 0;
let loaded = null; // { query, data } of the last answer, reused when only the chart metric changes

export async function render(root, reuse = false) {
  const query = `/stats?days=${view.days}${view.channel ? `&channel=${view.channel}` : ""}`;
  let data;
  if (reuse && loaded?.query === query) {
    data = loaded.data;
  } else {
    const request = ++latest;
    fill(root, head(() => render(root)), h("div", { class: "muted", text: "Loading…" }));
    try {
      data = await api.get(query);
    } catch (error) {
      showError(error);
      return;
    }
    // A newer range or store was picked while this one loaded.
    if (request !== latest) return;
    loaded = { query, data };
  }
  const t = data.totals;
  const reported = t.appOpens + t.serviceOpens + t.installs + data.daily.reduce((sum, d) => sum + d.activeUsers, 0);
  fill(root,
    head(() => render(root)),
    h("div", { class: "stats" },
      stat("Active users today", fmt(t.activeToday), `avg ${fmt(t.activeAverage)} / day · peak ${fmt(t.activePeak)}`),
      stat("API calls", fmt(t.apiCalls), `${pct(t.apiNotModified, t.apiCalls)} unchanged (304) · ${fmt(t.apiErrors)} errors`),
      stat("New installs", fmt(t.installs), "first launch of the app"),
      stat("App opens", fmt(t.appOpens), `${fmt(t.serviceOpens)} service opens`),
      stat("Searches", fmt(t.searches), `${pct(t.searchesWithoutResults, t.searches)} found nothing`),
      stat("Update clicks", fmt(t.updateClicks), `${fmt(t.forceUpdateShown)} hard · ${fmt(t.optionalUpdateShown)} soft prompts`),
      stat("Page load failures", fmt(t.loadFailures), "pages that showed an error")),
    h("div", { class: "stack" },
      chartCard(data.daily, () => render(root, true)),
      !reported && h("div", { class: "card card-body muted", text: "No app reports in this range yet. Apps send their totals when they go to the background (at most every 15 minutes) and at launch." }),
      servicesCard(data.services),
      h("div", { class: "grid-2 align-start" },
        barsCard("How services are opened", data.sources.map((s) => [SOURCES[s.source] || s.source, s.n])),
        barsCard("Categories opened", data.categories.map((c) => [categoryName(c.id), c.n])),
        tableCard("Stores", ["Store", "API calls", "Active users", "Installs"], data.channels.map((c) => [channelName(c.channel), fmt(c.apiCalls), fmt(c.activeUsers), fmt(c.installs)])),
        tableCard("App versions", ["versionCode", "API calls", "Active users", "Installs"], data.versions.map((v) => [v.version ? String(v.version) : "Unknown", fmt(v.apiCalls), fmt(v.activeUsers), fmt(v.installs)])),
        tableCard("API", ["Endpoint", "Result", "Calls"], data.api.map((a) => [ENDPOINTS[a.endpoint] || a.endpoint, statusChip(a.status), fmt(a.n)])),
        barsCard("Page errors", data.errors.map((e) => [ERRORS[e.error] || e.error, e.n]), "danger"),
        tableCard("Errors by service", ["Service", "Error", "Count"], data.failures.slice(0, 15).map((f) => [serviceName(f.service), ERRORS[f.error] || f.error, fmt(f.n)])),
        barsCard("Searches", [["Found services", t.searches - t.searchesWithoutResults], ["Found nothing", t.searchesWithoutResults]]),
        barsCard("Browsing data cleared", data.dataCleared.map((d) => [SCOPES[d.scope] || d.scope, d.n]))),
      h("p", { class: "hint", text: "API calls are counted by the server. Everything else comes from apps that share anonymous statistics (on by default; users can turn it off in Privacy): daily totals per install, with no identifier, address, search text or time of day. Reports can't be authenticated, so treat the numbers as estimates." })));
}

function head(refresh) {
  const range = h("div", { class: "seg", role: "group", "aria-label": "Range" },
    RANGES.map(([days, label]) => h("button", { class: "btn small", "aria-pressed": String(view.days === days), text: label, on: { click: () => { view.days = days; refresh(); } } })));
  const channel = h("select", { class: "input small-select", "aria-label": "Store", on: { change: (e) => { view.channel = e.target.value; refresh(); } } },
    CHANNELS.map(([value, label]) => h("option", { value, text: label, selected: view.channel === value })));
  return h("div", { class: "page-head" },
    h("div", { class: "grow" }, h("h1", { text: "Statistics" }), h("div", { class: "muted", text: "How the app is used, day by day (Iran time)." })),
    range, channel,
    h("button", { class: "btn icon", "aria-label": "Refresh", title: "Refresh", on: { click: refresh } }, icon("refresh")));
}

function stat(label, value, hint) {
  return h("div", { class: "card stat" }, h("div", { class: "muted small", text: label }), h("div", { class: "value", text: value }), hint && h("div", { class: "hint", text: hint }));
}

function chartCard(daily, rerender) {
  const metric = METRICS.find(([key]) => key === view.metric) || METRICS[0];
  const values = daily.map((d) => d[metric[0]]);
  const max = Math.max(1, ...values);
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  const step = 10;
  svg.setAttribute("viewBox", `0 0 ${daily.length * step} 100`);
  svg.setAttribute("preserveAspectRatio", "none");
  svg.setAttribute("class", "chart");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `${metric[1]} per day`);
  daily.forEach((d, i) => {
    const height = (d[metric[0]] / max) * 96;
    const bar = document.createElementNS(ns, "rect");
    bar.setAttribute("x", String(i * step + step * 0.15));
    bar.setAttribute("width", String(step * 0.7));
    bar.setAttribute("y", String(100 - Math.max(height, d[metric[0]] ? 1.5 : 0)));
    bar.setAttribute("height", String(Math.max(height, d[metric[0]] ? 1.5 : 0)));
    bar.setAttribute("rx", "1");
    const tip = document.createElementNS(ns, "title");
    tip.textContent = `${d.day}: ${fmt(d[metric[0]])}`;
    bar.append(tip);
    svg.append(bar);
  });
  const label = (day) => new Date(`${day}T12:00:00`).toLocaleDateString("en", { month: "short", day: "numeric" });
  const middle = daily[Math.floor((daily.length - 1) / 2)];
  return h("section", { class: "card" },
    h("div", { class: "card-head" },
      h("h2", { class: "grow", text: `${metric[1]} per day` }),
      h("div", { class: "seg", role: "group", "aria-label": "Metric" },
        METRICS.map(([key, name]) => h("button", { class: "btn small", "aria-pressed": String(view.metric === key), text: name, on: { click: () => { view.metric = key; rerender(); } } })))),
    h("div", { class: "card-body" },
      h("div", { class: "chart-wrap" },
        h("div", { class: "chart-max hint", text: fmt(max) }),
        svg),
      h("div", { class: "chart-axis hint" }, h("span", { text: label(daily[0].day) }), daily.length > 2 && h("span", { text: label(middle.day) }), h("span", { text: label(daily[daily.length - 1].day) }))));
}

function servicesCard(services) {
  const catalog = liveCatalog();
  const total = services.reduce((sum, s) => sum + s.opens, 0);
  const max = Math.max(1, ...services.map((s) => s.opens));
  return h("section", { class: "card" },
    h("div", { class: "card-head" }, h("h2", { class: "grow", text: "Services" }), h("span", { class: "chip", text: `${fmt(total)} opens` })),
    services.length === 0
      ? h("div", { class: "empty", text: "No service has been opened in this range." })
      : h("div", { class: "table-scroll" }, h("table", { class: "table" },
        h("thead", {}, h("tr", {}, ["Service", "Opens", "", "Tab switches", "Favorited", "Unfavorited", "Load errors"].map((label) => h("th", { text: label })))),
        h("tbody", {}, services.map((s) => {
          const service = catalog.services.find((x) => x.id === s.id) || { id: s.id, name: s.id };
          return h("tr", {},
            h("td", {}, h("div", { class: "row", style: { gap: "10px" } }, logo(service, 28), h("span", { class: "name", text: text(service.name, s.id) }))),
            h("td", { class: "num", text: fmt(s.opens) }),
            h("td", { class: "bar-cell" }, h("div", { class: "bar-track" }, h("div", { class: "bar-fill", style: { width: `${(s.opens / max) * 100}%` } })), h("span", { class: "hint", text: pct(s.opens, total) })),
            h("td", { class: "num", text: fmt(s.switches) }),
            h("td", { class: "num", text: s.favoritesAdded ? `+${fmt(s.favoritesAdded)}` : "—" }),
            h("td", { class: "num", text: s.favoritesRemoved ? `−${fmt(s.favoritesRemoved)}` : "—" }),
            h("td", { class: "num" }, s.failures ? h("span", { class: "chip danger", text: fmt(s.failures) }) : "—"));
        })))));
}

function barsCard(heading, rows, tone = "") {
  const max = Math.max(1, ...rows.map(([, n]) => n));
  const total = rows.reduce((sum, [, n]) => sum + n, 0);
  return h("section", { class: "card" },
    h("div", { class: "card-head" }, h("h2", { class: "grow", text: heading })),
    h("div", { class: "card-body" }, total === 0
      ? h("div", { class: "muted", text: "Nothing yet." })
      : h("div", { class: "bars" }, rows.map(([label, n]) => h("div", { class: "bar-row" },
        h("div", { class: "bar-label" }, h("span", { text: label }), h("span", { class: "muted", text: `${fmt(n)} · ${pct(n, total)}` })),
        h("div", { class: "bar-track" }, h("div", { class: `bar-fill ${tone}`, style: { width: `${(n / max) * 100}%` } })))))));
}

function tableCard(heading, columns, rows) {
  return h("section", { class: "card" },
    h("div", { class: "card-head" }, h("h2", { class: "grow", text: heading })),
    rows.length === 0
      ? h("div", { class: "card-body muted", text: "Nothing yet." })
      : h("div", { class: "table-scroll" }, h("table", { class: "table compact" },
        h("thead", {}, h("tr", {}, columns.map((c, i) => h("th", { class: i ? "num" : "", text: c })))),
        h("tbody", {}, rows.map((cells) => h("tr", {}, cells.map((c, i) => h("td", { class: i ? "num" : "" }, c))))))));
}

function statusChip(status) {
  const tone = { "2xx": "success", "304": "", "4xx": "warning", "5xx": "danger" }[status] ?? "";
  return h("span", { class: `chip ${tone}`, text: STATUSES[status] || status });
}

function liveCatalog() {
  return state.live?.catalog || state.draft?.catalog || { services: [], categories: [] };
}

function serviceName(id) {
  return text(liveCatalog().services.find((s) => s.id === id)?.name, id);
}

function categoryName(id) {
  return text(liveCatalog().categories.find((c) => c.id === id)?.title, id);
}

function channelName(id) {
  return (CHANNELS.find(([value]) => value === id) || [id, id])[1];
}
