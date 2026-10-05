// Settings: app-wide flags and rules from the catalog.
import { fill, h } from "../dom.js";
import { commit, state } from "../state.js";
import { applyProblems, linesField, numberField, section, showError, textField, toast, toggleField } from "../ui.js";

export const title = "Settings";

const FEATURES = [
  ["search", "Search", "The search field on Home."],
  ["favorites", "Favorites", "Stars and the favorites section."],
  ["multiProfile", "Profiles", "Separate sign-ins, e.g. personal and work (needs WebView support)."],
  ["compareMode", "Compare & choose", "Compare groups on Home and in the browser."],
  ["downloads", "Downloads", "Let services download files."],
  ["storageManager", "Storage", "The storage screen in Settings."],
];
const FEATURE_DEFAULTS = { search: true, favorites: true, multiProfile: false, compareMode: true, downloads: true, storageManager: true };

export function render(root) {
  const { catalog } = state.draft;
  const flags = Object.fromEntries(FEATURES.map(([key, label, hint]) => [key, toggleField({ label, hint, checked: catalog.features?.[key] ?? FEATURE_DEFAULTS[key] })]));
  const f = {
    refreshIntervalSeconds: numberField({ label: "Refresh interval (minutes)", value: Math.round((catalog.refreshIntervalSeconds || 3600) / 60), min: 5, hint: "How old the catalog may get before the app refreshes it on return. It always refreshes at launch. 5 minutes – 7 days." }),
    paymentDomains: linesField({ label: "Payment gateway domains", values: catalog.web?.paymentDomains, hint: "Always stay inside the service's tab, so payments return to the service.", placeholder: "shaparak.ir" }),
    externalSchemes: linesField({ label: "App schemes any service may open", values: catalog.web?.externalSchemes, hint: "e.g. tel, sms, geo, intent.", placeholder: "tel" }),
    privacyPolicyUrl: textField({ label: "Privacy policy URL", value: catalog.links?.privacyPolicyUrl, type: "url", dir: "ltr", placeholder: "https://" }),
    supportUrl: textField({ label: "Support URL", value: catalog.links?.supportUrl, type: "url", dir: "ltr", placeholder: "https://" }),
  };
  const save = h("button", { class: "btn primary", text: "Save to draft" });
  save.addEventListener("click", async () => {
    save.disabled = true;
    try {
      await commit((d) => {
        d.catalog.refreshIntervalSeconds = Math.round((f.refreshIntervalSeconds.value ?? 60) * 60);
        d.catalog.features = { ...(d.catalog.features || {}), ...Object.fromEntries(Object.entries(flags).map(([k, field]) => [k, field.value])) };
        d.catalog.web = { ...(d.catalog.web || {}), paymentDomains: f.paymentDomains.value, externalSchemes: f.externalSchemes.value };
        d.catalog.links = { ...(d.catalog.links || {}), privacyPolicyUrl: f.privacyPolicyUrl.value || null, supportUrl: f.supportUrl.value || null };
      });
      toast("Saved to draft");
    } catch (error) {
      applyProblems(error.problems || [], "catalog", { refreshIntervalSeconds: f.refreshIntervalSeconds, web: f.paymentDomains, links: f.privacyPolicyUrl });
      applyProblems(error.problems || [], "catalog.links", f);
      showError(error);
    } finally {
      save.disabled = false;
    }
  });
  fill(root, 
    h("div", { class: "page-head" }, h("div", { class: "grow" }, h("h1", { text: "Settings" }), h("div", { class: "muted", text: "App-wide switches and rules." })), save),
    h("div", { class: "stack" },
      section("Features", h("div", { class: "grid-2" }, Object.values(flags).map((x) => x.el))),
      section("Refresh", f.refreshIntervalSeconds.el),
      section("Web rules for every service", f.paymentDomains.el, f.externalSchemes.el),
      section("Links in the app's Settings", f.privacyPolicyUrl.el, f.supportUrl.el)));
}
