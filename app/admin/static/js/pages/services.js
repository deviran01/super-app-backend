// Services: the apps users open. Grouped by category in display order; drag to reorder
// within a category, switch them on and off, edit everything the app supports.
import { fill, h, icon } from "../dom.js";
import { commit, host, imageUrl, renumber, sortedCategories, sortedServices, state, text } from "../state.js";
import {
  advanced, applyProblems, colorField, confirm, dragHandle, drawer, imageField, linesField, localizedField,
  section, selectField, showError, sortable, textField, toast, toggleField,
} from "../ui.js";

let query = "";
let categoryFilter = "all";

export const title = "Services";

export function render(root) {
  const { catalog } = state.draft;
  const categories = sortedCategories(catalog);
  const services = sortedServices(catalog);
  const q = query.trim().toLowerCase();
  const matches = (s) => !q || [s.id, s.url, s.name?.fa, s.name?.en, ...(s.keywords || [])].some((v) => (v || "").toLowerCase().includes(q));

  const search = h("input", { class: "input", type: "search", placeholder: "Search services", value: query, "aria-label": "Search services" });
  search.addEventListener("input", () => {
    query = search.value;
    render(root);
    const again = root.querySelector("input[type=search]");
    again.focus();
    again.setSelectionRange(again.value.length, again.value.length);
  });
  const filter = h("select", { class: "input", style: { width: "auto" }, "aria-label": "Category",
    on: { change: (e) => { categoryFilter = e.target.value; render(root); } } },
    h("option", { value: "all", text: "All categories", selected: categoryFilter === "all" }),
    categories.map((c) => h("option", { value: c.id, text: text(c.title, c.id), selected: categoryFilter === c.id })));

  const enabled = services.filter((s) => s.enabled !== false).length;
  fill(root, 
    h("div", { class: "page-head" },
      h("div", { class: "grow" }, h("h1", { text: "Services" }), h("div", { class: "muted", text: `${services.length} services · ${enabled} enabled` })),
      h("div", { class: "search" }, icon("search"), search),
      filter,
      h("button", { class: "btn primary", on: { click: () => edit(null) } }, icon("plus"), "Add service")),
    q && h("div", { class: "hint", style: { marginBottom: "10px" }, text: "Clear the search to drag services into a new order." }),
    categories
      .filter((c) => categoryFilter === "all" || c.id === categoryFilter)
      .map((category) => {
        const items = services.filter((s) => s.categoryId === category.id && matches(s));
        if (!items.length && (q || categoryFilter === "all")) return null;
        const list = h("ul", { class: "list card" }, items.map((s) => row(s, Boolean(q))));
        sortable(list, (ids) => reorder(ids));
        return h("div", { class: "group" },
          h("div", { class: "group-head" }, h("span", { class: "dot", style: { background: category.color || "var(--accent)" } }), text(category.title, category.id),
            h("span", { class: "chip", text: String(items.length) }), category.enabled === false && h("span", { class: "chip warning", text: "Category hidden" })),
          items.length ? list : h("div", { class: "card empty", text: "No services in this category yet." }));
      }),
  );
}

function logo(service, size = 40) {
  const monogram = () => h("div", { class: "logo placeholder-logo", style: { background: service.brandColor || "var(--text-3)" }, text: (text(service.name, service.id) || "?").slice(0, 1) });
  const src = imageUrl(service.logo);
  if (!src) return monogram();
  // A missing file falls back to the letter, like the app does.
  const img = h("img", { class: "logo", src, alt: "", width: size, height: size, loading: "lazy" });
  img.addEventListener("error", () => img.replaceWith(monogram()), { once: true });
  return img;
}

function row(service, searching) {
  const off = service.enabled === false;
  const toggle = h("input", { type: "checkbox", checked: !off, "aria-label": `${text(service.name)} enabled` });
  toggle.addEventListener("change", () => update(service.id, (s) => { s.enabled = toggle.checked; }, toggle.checked ? "Enabled" : "Disabled"));
  return h("li", { class: `item ${off ? "disabled" : ""}`, dataset: { id: service.id } },
    dragHandle(text(service.name, service.id), searching),
    logo(service),
    h("div", { class: "grow" },
      h("div", { class: "row", style: { gap: "8px" } },
        h("span", { class: "name", text: text(service.name, service.id) }),
        service.name?.en && service.name?.fa && h("span", { class: "muted small", text: service.name.en }),
        service.featured && h("span", { class: "chip accent" }, icon("star"), "Featured"),
        service.maintenance && h("span", { class: "chip warning" }, icon("wrench"), "Maintenance"),
        service.compatibility && service.compatibility !== "SUPPORTED" && h("span", { class: "chip", text: service.compatibility.toLowerCase() })),
      h("div", { class: "sub ltr", text: `${service.id} · ${host(service.url)}` })),
    h("label", { class: "switch", title: off ? "Disabled" : "Enabled" }, toggle, h("span", { class: "track" })),
    h("button", { class: "btn ghost icon", "aria-label": `Edit ${text(service.name)}`, on: { click: () => edit(service.id) } }, icon("edit")),
    h("button", { class: "btn ghost icon danger", "aria-label": `Delete ${text(service.name)}`, on: { click: () => remove(service.id) } }, icon("trash")));
}

async function update(id, change, message) {
  try {
    await commit((d) => change(d.catalog.services.find((s) => s.id === id)));
    toast(`${message} — in draft`);
  } catch (error) {
    showError(error);
  }
}

async function reorder(ids) {
  try {
    await commit((d) => {
      ids.forEach((id, i) => { d.catalog.services.find((s) => s.id === id).order = i; });
      renumber(d.catalog);
    });
  } catch (error) {
    showError(error);
  }
}

async function remove(id) {
  const { catalog } = state.draft;
  const service = catalog.services.find((s) => s.id === id);
  const groups = (catalog.compareGroups || []).filter((g) => g.serviceIds.includes(id));
  const ok = await confirm({
    title: `Delete “${text(service.name, id)}”?`,
    message: `It disappears from the app when you publish. Open tabs explain that it was removed.${groups.length ? ` It also leaves ${groups.length} compare group(s).` : ""} Prefer switching it off if it may come back.`,
    confirmLabel: "Delete",
    danger: true,
  });
  if (!ok) return;
  try {
    await commit((d) => {
      d.catalog.services = d.catalog.services.filter((s) => s.id !== id);
      for (const group of d.catalog.compareGroups || []) group.serviceIds = group.serviceIds.filter((sid) => sid !== id);
      // A comparison needs two services.
      d.catalog.compareGroups = (d.catalog.compareGroups || []).filter((g) => g.serviceIds.length >= 2);
      renumber(d.catalog);
    });
    toast("Deleted — in draft");
  } catch (error) {
    showError(error);
  }
}

const POPUP = [["NEW_TAB", "New tab, linked to the page (payments work)"], ["SAME_TAB", "Same tab"], ["EXTERNAL_BROWSER", "External browser"], ["BLOCK", "Block"]];
const OFF_DOMAIN = [["STAY_IN_TAB", "Stay in the tab"], ["OPEN_EXTERNALLY", "Open in the external browser"]];
const CACHE = [["DEFAULT", "Default"], ["PREFER_CACHE", "Prefer cache (offline friendly)"], ["NO_CACHE", "No cache"]];
const KEEP_ALIVE = [["HIGH", "High — keep alive (rides, deliveries)"], ["NORMAL", "Normal"], ["LOW", "Low — release first"]];
const COMPATIBILITY = [["SUPPORTED", "Supported"], ["PARTIAL", "Partial"], ["EXPERIMENTAL", "Experimental"], ["DISABLED", "Disabled"]];
const AGENT = [["DEFAULT", "Default (WebView)"], ["STRIP_WEBVIEW_MARKER", "Remove the WebView marker"], ["CUSTOM", "Custom"]];
const options = (pairs) => pairs.map(([value, label]) => ({ value, label }));

function edit(id) {
  const { catalog } = state.draft;
  const existing = id ? catalog.services.find((s) => s.id === id) : null;
  const s = existing || { enabled: true, web: { permissions: {} }, categoryId: sortedCategories(catalog)[0]?.id };
  const web = s.web || {};

  const f = {
    id: textField({ label: "ID", value: s.id, mono: true, disabled: Boolean(existing), placeholder: "snapp", hint: existing ? "Can't change: open tabs and favorites use it." : "Lowercase letters, digits, - or _. Permanent." }),
    name: localizedField({ label: "Name", value: s.name, maxLength: 64 }),
    description: localizedField({ label: "Description", value: s.description, maxLength: 240, multiline: true }),
    categoryId: selectField({ label: "Category", value: s.categoryId, options: sortedCategories(catalog).map((c) => ({ value: c.id, label: text(c.title, c.id) })) }),
    url: textField({ label: "Start URL", value: s.url, type: "url", placeholder: "https://app.example.ir/", dir: "ltr", hint: "Where the service opens. HTTPS only." }),
    brandColor: colorField({ label: "Brand color", value: s.brandColor, hint: "Behind the logo while it loads, and featured banners." }),
    featured: toggleField({ label: "Featured", checked: s.featured, hint: "Shown in the featured row on Home." }),
    enabled: toggleField({ label: "Enabled", checked: s.enabled !== false, hint: "Off: hidden from users; open tabs say it was removed." }),
    compatibility: selectField({ label: "Compatibility", value: s.compatibility || "SUPPORTED", options: options(COMPATIBILITY) }),
    badge: localizedField({ label: "Badge", value: s.badge, maxLength: 16, hint: "A short label on the tile, e.g. “New”." }),
    keywords: linesField({ label: "Search keywords", values: s.keywords, hint: "One per line or comma separated; Persian and English." }),
  };
  f.logo = imageField({ label: "Logo", kind: "logo", value: s.logo, getName: () => existing?.id || f.id.value, hint: "Square app icon. PNG, JPEG or WebP; resized to 256 px." });
  const maintenanceOn = toggleField({ label: "Under maintenance", checked: Boolean(s.maintenance), hint: "Users see this message instead of the service." });
  const maintenanceMessage = localizedField({ label: "Maintenance message", value: s.maintenance?.message, maxLength: 400, multiline: true });
  const w = {
    allowedDomains: linesField({ label: "Allowed domains", values: web.allowedDomains, hint: "Domains that stay in the tab (subdomains included). The start URL's host is always allowed.", placeholder: "snapp.ir" }),
    location: toggleField({ label: "Location", checked: web.permissions?.location }),
    camera: toggleField({ label: "Camera", checked: web.permissions?.camera }),
    microphone: toggleField({ label: "Microphone", checked: web.permissions?.microphone }),
    popupPolicy: selectField({ label: "Popups (window.open)", value: web.popupPolicy || "NEW_TAB", options: options(POPUP) }),
    offDomainNavigation: selectField({ label: "Links to other sites", value: web.offDomainNavigation || "STAY_IN_TAB", options: options(OFF_DOMAIN) }),
    externalDomains: linesField({ label: "Always open externally", values: web.externalDomains, hint: "Domains that open in the system browser (help center, blog).", placeholder: "blog.example.ir" }),
    externalSchemes: linesField({ label: "Extra app schemes", values: web.externalSchemes, hint: "Schemes this service may open without asking, e.g. its bank app.", placeholder: "snapp" }),
    thirdPartyCookies: toggleField({ label: "Third-party cookies", checked: web.thirdPartyCookies !== false, hint: "Needed by embedded sign-in and payment frames." }),
    javascript: toggleField({ label: "JavaScript", checked: web.javascript !== false }),
    domStorage: toggleField({ label: "Local storage", checked: web.domStorage !== false }),
    fileUpload: toggleField({ label: "File uploads", checked: web.fileUpload !== false }),
    downloads: toggleField({ label: "Downloads", checked: web.downloads !== false }),
    restoreLastUrl: toggleField({ label: "Reopen the last page", checked: web.restoreLastUrl !== false, hint: "After the app was closed; off: always the start URL." }),
    cacheMode: selectField({ label: "Cache", value: web.cacheMode || "DEFAULT", options: options(CACHE) }),
    keepAlive: selectField({ label: "Keep alive", value: web.keepAlive || "NORMAL", options: options(KEEP_ALIVE), hint: "How long the page stays loaded in the background on low memory." }),
    agentMode: selectField({ label: "User agent", value: web.userAgent?.mode || "DEFAULT", options: options(AGENT), hint: "Try “Remove the WebView marker” for sites that refuse WebView." }),
    agentValue: textField({ label: "Custom user agent", value: web.userAgent?.value, mono: true }),
    errorMessage: localizedField({ label: "Message when unreachable", value: web.errorPage?.message, maxLength: 400, multiline: true }),
    errorHelp: textField({ label: "Help link when unreachable", value: web.errorPage?.helpUrl, type: "url", dir: "ltr", placeholder: "https://status.example.ir" }),
  };

  let index = -1;
  drawer({
    title: existing ? `Edit ${text(s.name, s.id)}` : "Add a service",
    subtitle: existing ? `${s.id} · changes go to the draft until you publish` : "It appears in the app after you publish",
    body: [
      section("Basics", f.name.el, f.id.el, f.url.el, f.categoryId.el, f.description.el),
      section("Look", f.logo.el, f.brandColor.el, f.badge.el, h("div", { class: "grid-2" }, f.featured.el, f.enabled.el)),
      section("Discovery", f.keywords.el, f.compatibility.el),
      section("Maintenance", maintenanceOn.el, maintenanceMessage.el),
      advanced("Web behavior", w.allowedDomains.el, h("div", { class: "label", text: "Permissions the page may ask for" }), h("div", { class: "grid-3" }, w.location.el, w.camera.el, w.microphone.el),
        w.popupPolicy.el, w.offDomainNavigation.el, w.externalDomains.el, w.externalSchemes.el,
        h("div", { class: "grid-2" }, w.thirdPartyCookies.el, w.javascript.el, w.domStorage.el, w.fileUpload.el, w.downloads.el, w.restoreLastUrl.el),
        h("div", { class: "grid-2" }, w.cacheMode.el, w.keepAlive.el), w.agentMode.el, w.agentValue.el, w.errorMessage.el, w.errorHelp.el),
    ],
    onProblems: (problems) => applyProblems(problems, `catalog.services[${index}]`, { ...f, maintenance: maintenanceMessage, web: w.allowedDomains }),
    onSave: async () => {
      const serviceId = existing ? existing.id : f.id.value;
      const next = {
        ...(existing || {}),
        id: serviceId,
        name: f.name.value,
        description: f.description.value,
        categoryId: f.categoryId.value,
        url: f.url.value,
        logo: f.logo.value,
        brandColor: f.brandColor.value,
        featured: f.featured.value,
        enabled: f.enabled.value,
        compatibility: f.compatibility.value,
        badge: f.badge.value,
        keywords: f.keywords.value,
        maintenance: maintenanceOn.value ? { message: maintenanceMessage.value } : null,
        web: {
          ...(existing?.web || {}),
          allowedDomains: w.allowedDomains.value,
          permissions: { location: w.location.value, camera: w.camera.value, microphone: w.microphone.value },
          popupPolicy: w.popupPolicy.value,
          offDomainNavigation: w.offDomainNavigation.value,
          externalDomains: w.externalDomains.value,
          externalSchemes: w.externalSchemes.value,
          thirdPartyCookies: w.thirdPartyCookies.value,
          javascript: w.javascript.value,
          domStorage: w.domStorage.value,
          fileUpload: w.fileUpload.value,
          downloads: w.downloads.value,
          restoreLastUrl: w.restoreLastUrl.value,
          cacheMode: w.cacheMode.value,
          keepAlive: w.keepAlive.value,
          userAgent: w.agentMode.value === "DEFAULT" ? null : { mode: w.agentMode.value, value: w.agentMode.value === "CUSTOM" ? w.agentValue.value : null },
          errorPage: w.errorMessage.value || w.errorHelp.value ? { message: w.errorMessage.value, helpUrl: w.errorHelp.value || null } : null,
        },
      };
      if (!existing && state.draft.catalog.services.some((x) => x.id === serviceId)) {
        f.id.setError("Another service already uses this ID");
        throw new Error("Choose another ID");
      }
      await commit((d) => {
        if (existing) {
          d.catalog.services[d.catalog.services.findIndex((x) => x.id === existing.id)] = next;
        } else {
          next.order = 1_000_000; // last in its category
          d.catalog.services.push(next);
        }
        renumber(d.catalog);
        index = d.catalog.services.findIndex((x) => x.id === serviceId);
      });
      toast(existing ? "Saved to draft" : "Added to draft");
    },
  });
}
