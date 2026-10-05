// Releases: the update policy the API answers per store (GET /api/v1/app/version).
import { fill, h, icon } from "../dom.js";
import { commit, state } from "../state.js";
import { applyProblems, dialog, localizedField, numberField, section, selectField, showError, textField, toast, toggleField } from "../ui.js";

export const title = "Releases";

const STORES = {
  bazaar: { name: "Cafe Bazaar", page: "https://cafebazaar.ir/app/io.celin.super.app" },
  myket: { name: "Myket", page: "https://myket.ir/app/io.celin.super.app" },
  direct: { name: "Website (direct APK)", page: "" },
};

function effective(release, channel) {
  const rule = { ...release.default, ...(channel ? release.channels?.[channel] : {}) };
  const minimum = rule.minimumSupportedVersion ?? 0;
  const latest = Math.max(rule.latestVersion ?? minimum, minimum);
  const blockedBelow = rule.forceUpdate ? latest : minimum;
  return { ...rule, minimum, latest, blockedBelow };
}

function effect(rule) {
  return h("div", { class: "effect" },
    h("div", {}, h("strong", { text: "Hard update: " }), rule.blockedBelow > 0 ? `builds below ${rule.blockedBelow} are blocked until they update.` : "nobody is blocked."),
    h("div", {}, h("strong", { text: "Soft update: " }), rule.latest > rule.blockedBelow ? `builds ${rule.blockedBelow} – ${rule.latest - 1} see the “update available” banner.` : "no banner."),
    h("div", {}, h("strong", { text: "Update opens: " }), h("span", { class: "ltr", text: rule.updateUrl || "nothing (button hidden)" })));
}

export function render(root) {
  const { release } = state.draft;
  const channels = Object.keys(release.channels || {});
  fill(root, 
    h("div", { class: "page-head" },
      h("div", { class: "grow" }, h("h1", { text: "Releases" }),
        h("div", { class: "muted", text: "Soft and hard updates per store. The app checks this on every launch and every return to the app." })),
      h("button", { class: "btn", on: { click: addChannel } }, icon("plus"), "Add store")),
    h("div", { class: "card card-body", style: { marginBottom: "16px" } },
      h("strong", { text: "Before raising a version: " }),
      "raise a store's numbers only after that store has approved and published the release. A hard update pointing to a store page without the update locks those users out."),
    h("div", { class: "stack" }, ruleCard(null), channels.map((c) => ruleCard(c))));
}

function ruleCard(channel) {
  const { release } = state.draft;
  const rule = channel ? release.channels[channel] || {} : release.default;
  const inherited = channel ? effective(release, null) : null;
  const store = STORES[channel] || { name: channel, page: "" };
  const f = {
    minimumSupportedVersion: numberField({ label: "Minimum version (hard update)", value: rule.minimumSupportedVersion, placeholder: inherited ? `Default: ${inherited.minimum}` : "", hint: "versionCode. Lower builds are blocked." }),
    latestVersion: numberField({ label: "Latest version (soft update)", value: rule.latestVersion, placeholder: inherited ? `Default: ${inherited.latest}` : "", hint: "versionCode live in this store. Lower builds see a banner." }),
    updateUrl: textField({ label: channel ? "Store page" : "Download page (website builds)", value: rule.updateUrl, type: "url", dir: "ltr", placeholder: store.page || "https://", hint: channel ? "What “Update” opens after the store app itself." : "Used by builds without a store page of their own." }),
    message: localizedField({ label: "Message on the blocking screen", value: rule.message, maxLength: 400, multiline: true, hint: channel ? "Empty: the default message." : "" }),
    optionalMessage: localizedField({ label: "Message on the update banner", value: rule.optionalMessage, maxLength: 400, multiline: true, hint: channel ? "Empty: the default message." : "" }),
  };
  f.forceUpdate = channel
    ? selectField({ label: "Force update", value: rule.forceUpdate == null ? "inherit" : String(rule.forceUpdate), options: [{ value: "inherit", label: `Default (${inherited.forceUpdate ? "on" : "off"})` }, { value: "true", label: "On — block every build below the latest" }, { value: "false", label: "Off" }] })
    : toggleField({ label: "Force update", checked: rule.forceUpdate, hint: "Kill switch: block every build below the latest version." });

  const save = h("button", { class: "btn primary", text: "Save to draft" });
  save.addEventListener("click", async () => {
    const next = {
      ...rule,
      minimumSupportedVersion: f.minimumSupportedVersion.value,
      latestVersion: f.latestVersion.value,
      forceUpdate: channel ? (f.forceUpdate.value === "inherit" ? null : f.forceUpdate.value === "true") : f.forceUpdate.value,
      updateUrl: f.updateUrl.value || null,
      message: f.message.value,
      optionalMessage: f.optionalMessage.value,
    };
    const latest = next.latestVersion ?? (channel ? inherited.latest : next.minimumSupportedVersion);
    const minimum = next.minimumSupportedVersion ?? (channel ? inherited.minimum : 0);
    if (latest != null && minimum != null && latest < minimum) {
      f.latestVersion.setError("Can't be lower than the minimum version");
      return;
    }
    save.disabled = true;
    try {
      await commit((d) => { if (channel) d.release.channels[channel] = next; else d.release.default = next; });
      toast("Saved to draft");
    } catch (error) {
      applyProblems(error.problems || [], channel ? `release.channels.${channel}` : "release.default", f);
      showError(error);
    } finally {
      save.disabled = false;
    }
  });
  const remove = channel && h("button", { class: "btn ghost danger", text: "Remove store", on: { click: async () => {
    try { await commit((d) => { delete d.release.channels[channel]; }); toast("Removed — in draft"); } catch (error) { showError(error); }
  } } });
  return h("section", { class: "card" },
    h("div", { class: "card-head" }, h("div", { class: "grow" }, h("h2", { text: channel ? store.name : "Default — every build" }), h("div", { class: "muted small ltr", text: channel ? `channel=${channel} · empty fields use the default` : "Applies unless a store below overrides a field" })), remove),
    h("div", { class: "section" }, effect(effective(state.draft.release, channel)),
      h("div", { class: "grid-2" }, f.minimumSupportedVersion.el, f.latestVersion.el), f.forceUpdate.el, f.updateUrl.el, f.message.el, f.optionalMessage.el,
      h("div", { class: "row", style: { justifyContent: "flex-end" } }, save)));
}

async function addChannel() {
  const field = textField({ label: "Store channel", placeholder: "bazaar", mono: true, hint: "The build's channel: bazaar, myket, direct, or a new store's flavor name." });
  const ok = await dialog({ title: "Add store", body: field.el, actions: (close) => [h("button", { class: "btn", text: "Cancel", on: { click: () => close(false) } }), h("button", { class: "btn primary", text: "Add", on: { click: () => close(true) } })] });
  const channel = field.value.toLowerCase();
  if (!ok || !channel) return;
  if (state.draft.release.channels?.[channel]) return showError("That store is already listed");
  try {
    await commit((d) => { d.release.channels = d.release.channels || {}; d.release.channels[channel] = STORES[channel]?.page ? { updateUrl: STORES[channel].page } : {}; });
  } catch (error) { showError(error); }
}
