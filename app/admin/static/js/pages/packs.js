// Packs: sets of services switched on and off together, e.g. Iranian sites that stay reachable
// when international internet is cut. A switched-off pack stays in the catalog; the app gets
// only switched-on ones, added to the catalog, or alone for a pack that replaces it. Packs
// that ship with the code are added to the draft from here; the switch acts on the live
// version right away (it publishes only itself).
import { api } from "../api.js";
import { fill, h, icon } from "../dom.js";
import { addPack, commit, renumber, servedServices, setMode, sortedCategories, state, switchPack, text } from "../state.js";
import { confirm, showError, toast } from "../ui.js";
import { showPack } from "./services.js";

export const title = "Packs";

export async function render(root) {
  let bundled = [];
  try {
    bundled = await api.get("/packs");
  } catch (error) {
    showError(error);
  }
  const { catalog } = state.draft;
  const inDraft = catalog.packs || [];
  const notAdded = bundled.filter((b) => !inDraft.some((p) => p.id === b.id));
  fill(root,
    h("div", { class: "page-head" },
      h("div", { class: "grow" }, h("h1", { text: "Packs" }),
        h("div", { class: "muted", text: "Sets of services you switch on together, e.g. Iranian sites for when international internet is cut. A switched-off pack stays here but the app doesn't get it; a pack that replaces the catalog is shown on its own. The switch is live right away: it publishes only itself." }))),
    h("div", { class: "stack" },
      inDraft.map((pack) => packCard(pack, bundled.find((b) => b.id === pack.id))),
      notAdded.map(bundledCard),
      !inDraft.length && !notAdded.length && h("div", { class: "card empty", text: "No packs." })));
}

function packCard(pack, bundle) {
  const { catalog } = state.draft;
  const live = (state.live.catalog.packs || []).find((p) => p.id === pack.id);
  const services = catalog.services.filter((s) => s.pack === pack.id);
  const categories = catalog.categories.filter((c) => c.pack === pack.id);
  const enabled = services.filter((s) => s.enabled !== false).length;
  // The switch shows and changes what users have: the live version.
  const toggle = h("input", { type: "checkbox", checked: Boolean(live?.active), disabled: !live, "aria-label": `${text(pack.title, pack.id)} switched on for users` });
  toggle.addEventListener("change", async () => {
    const wanted = toggle.checked;
    toggle.checked = !wanted; // until it's done; a successful switch re-renders the page
    await switchLive(live, wanted);
  });
  // Only after a restore or an edit to the draft's own copy of the switch.
  const pending = live && Boolean(live.active) !== Boolean(pack.active);
  const fresh = bundle ? bundle.new_services + bundle.new_categories + bundle.new_compareGroups : 0;
  return h("section", { class: "card" },
    h("div", { class: "card-head", style: { flexWrap: "wrap" } },
      h("div", { class: "grow", style: { minWidth: "12em" } }, h("h2", { dir: "auto", text: text(pack.title, pack.id) }), pack.title?.en && pack.title?.fa && h("div", { class: "muted small", text: pack.title.en })),
      pack.exclusive && h("span", { class: "chip", title: "While it's on, the app gets only this pack", text: "Replaces the catalog" }),
      h("span", { class: `chip ${live?.active ? "success" : ""}`, text: live ? (live.active ? "Live: on" : "Live: off") : "Not published yet" }),
      pending && h("span", { class: "chip warning", text: pack.active ? "On after you publish" : "Off after you publish" }),
      h("label", { class: "switch", title: !live ? "Publish the pack first" : live.active ? "On for users" : "Off for users" }, toggle, h("span", { class: "track" }))),
    h("div", { class: "card-body stack", style: { gap: "12px" } },
      pack.description && h("div", { class: "muted", dir: "auto", text: text(pack.description) }),
      h("div", { text: `${services.length} services (${enabled} enabled), ${categories.length} categories of its own, ${services.filter((s) => !categories.some((c) => c.id === s.categoryId)).length} services in the catalog's categories.` }),
      h("div", { class: "row", style: { gap: "6px", flexWrap: "wrap" } }, breakdown(services).map(([category, count]) =>
        h("span", { class: "chip", dir: "auto", text: `${text(category?.title, "?")} ${count}` }))),
      fresh > 0 && h("div", { class: "row", style: { gap: "10px", flexWrap: "wrap" } },
        h("span", { class: "hint", text: `The pack that came with this version has ${describe(bundle)} that aren't in the catalog (new, or deleted here).` }),
        h("button", { class: "btn small", on: { click: () => add(bundle) } }, icon("plus"), "Add them to the draft")),
      h("div", { class: "row", style: { gap: "8px", flexWrap: "wrap" } },
        h("button", { class: "btn small", on: { click: () => { showPack(pack.id); location.hash = "#/services"; } } }, icon("apps"), "Show its services"),
        h("div", { class: "grow", style: { flex: 1 } }),
        h("button", { class: "btn ghost small danger", on: { click: () => remove(pack) } }, icon("trash"), "Remove from the catalog"))));
}

function bundledCard(bundle) {
  return h("section", { class: "card" },
    h("div", { class: "card-head", style: { flexWrap: "wrap" } },
      h("div", { class: "grow", style: { minWidth: "12em" } }, h("h2", { dir: "auto", text: text(bundle.title, bundle.id) }), bundle.title?.en && bundle.title?.fa && h("div", { class: "muted small", text: bundle.title.en })),
      bundle.exclusive && h("span", { class: "chip", title: "While it's on, the app gets only this pack", text: "Replaces the catalog" }),
      h("span", { class: "chip", text: "Not in the catalog" })),
    h("div", { class: "card-body stack", style: { gap: "12px" } },
      bundle.description && h("div", { class: "muted", dir: "auto", text: text(bundle.description) }),
      h("div", { text: `Ships with this version: ${describe(bundle)}. Adding puts them in the draft switched off — users see nothing until you switch the pack on and publish.` }),
      h("div", {}, h("button", { class: "btn primary", on: { click: () => add(bundle) } }, icon("plus"), "Add to the draft"))));
}

function describe(bundle) {
  const parts = [[bundle.new_services, "service"], [bundle.new_categories, "category", "categories"], [bundle.new_compareGroups, "compare group"]];
  return parts.filter(([n]) => n > 0).map(([n, one, many]) => `${n} ${n === 1 ? one : many || `${one}s`}`).join(", ") || "nothing new";
}

/** [category, number of the pack's services in it], in the catalog's order. */
function breakdown(services) {
  return sortedCategories(state.draft.catalog)
    .map((category) => [category, services.filter((s) => s.categoryId === category.id).length])
    .filter(([, count]) => count > 0);
}

async function add(bundle) {
  try {
    await addPack(bundle.id);
    toast("Added to the draft — publish when ready");
  } catch (error) {
    showError(error);
  }
}

/**
 * Switches a published pack for users right away, after a confirmation. Publishes only the
 * switch: other unpublished changes stay in the draft. A pack that replaces the catalog is on
 * alone (the server switches the others off).
 */
export async function switchLive(pack, active) {
  const live = state.live.catalog;
  const packs = live.packs || [];
  const after = active
    ? packs.map((p) => ({ ...p, active: p.id === pack.id || (Boolean(p.active) && !pack.exclusive && !p.exclusive) }))
    : packs.map((p) => ({ ...p, active: p.id !== pack.id && Boolean(p.active) }));
  const name = text(pack.title, pack.id);
  return confirmSwitch(packs, after, {
    title: active ? `Switch on “${name}” for users?` : `Switch off “${name}” for users?`,
    confirmLabel: active ? "Switch on now" : "Switch off now",
    danger: !active,
    run: () => switchPack(pack.id, active),
    done: active ? "Switched on — live now" : "Switched off — live now",
  });
}

/** The app mode (Overview): the current catalog (null), or with exactly [pack] switched on. */
export async function chooseMode(pack) {
  const packs = state.live.catalog.packs || [];
  const after = packs.map((p) => ({ ...p, active: Boolean(pack) && p.id === pack.id }));
  return confirmSwitch(packs, after, {
    title: pack ? `Switch the app to “${text(pack.title, pack.id)}”?` : "Switch the app back to the current catalog?",
    confirmLabel: "Switch now",
    danger: false,
    run: () => setMode(pack ? pack.id : null),
    done: "Switched — live now",
  });
}

async function confirmSwitch(before, after, { run, done, ...dialog }) {
  const live = state.live.catalog;
  const count = (packs) => servedServices({ ...live, packs }).length;
  const name = (p) => `“${text(p.title, p.id)}”`;
  const alone = after.find((p) => p.active && p.exclusive);
  const offToo = before.filter((p) => p.active && !after.find((q) => q.id === p.id)?.active);
  const lines = [
    alone ? `Users get only ${name(alone)}: ${count(after)} services, instead of ${count(before)} now. The current catalog's services leave the app until you switch back.`
      : `Users get ${count(after)} services, instead of ${count(before)} now.`,
    offToo.length > 1 || (offToo.length === 1 && !dialog.danger) ? `This switches off ${offToo.map(name).join(" and ")}.` : "",
    "It's live the next time the app opens or refreshes its catalog. Only the switch is published: other unpublished changes stay in the draft.",
  ];
  if (!(await confirm({ ...dialog, message: lines.filter(Boolean).join(" ") }))) return false;
  try {
    await run();
    toast(done);
    return true;
  } catch (error) {
    showError(error);
    return false;
  }
}

async function remove(pack) {
  const { catalog } = state.draft;
  const services = catalog.services.filter((s) => s.pack === pack.id).length;
  const categories = catalog.categories.filter((c) => c.pack === pack.id).length;
  const ok = await confirm({
    title: `Remove “${text(pack.title, pack.id)}”?`,
    message: `Its ${services} services and ${categories} categories leave the catalog when you publish, with any edits made to them here. If the pack ships with the code, you can add it again later.`,
    confirmLabel: "Remove",
    danger: true,
  });
  if (!ok) return;
  try {
    await commit((d) => {
      const c = d.catalog;
      c.packs = (c.packs || []).filter((p) => p.id !== pack.id);
      c.services = c.services.filter((s) => s.pack !== pack.id);
      c.categories = c.categories.filter((x) => x.pack !== pack.id);
      const left = new Set(c.services.map((s) => s.id));
      c.compareGroups = (c.compareGroups || [])
        .filter((g) => g.pack !== pack.id)
        .map((g) => ({ ...g, serviceIds: g.serviceIds.filter((sid) => left.has(sid)) }))
        .filter((g) => g.serviceIds.length >= 2);
      c.categories.sort((a, b) => a.order - b.order);
      renumber(c);
    });
    toast("Removed — in draft");
  } catch (error) {
    showError(error);
  }
}
