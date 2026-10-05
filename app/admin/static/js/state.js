// The dashboard's view of the draft. Pages read `state.draft` and change it only through
// commit(), which saves the whole draft to the server (validated there, with the revision
// the change was based on, so two admins can't silently overwrite each other).
import { api } from "./api.js";

export const state = {
  user: null,
  draft: null,
  live: null,
  revision: 0,
  dirty: false,
  published: {},
  updatedBy: null,
  updatedAt: null,
};

const listeners = new Set();
export function subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); }
function notify() { for (const fn of listeners) fn(); }

function apply(response) {
  Object.assign(state, {
    draft: response.draft,
    live: response.live,
    revision: response.revision,
    dirty: response.dirty,
    published: response.published || {},
    updatedBy: response.updatedBy,
    updatedAt: response.updatedAt,
  });
  notify();
}

export async function loadState() { apply(await api.get("/state")); }

/** Applies `mutate` to a copy of the draft and saves it. Throws ApiError with `problems`. */
export async function commit(mutate) {
  const next = structuredClone(state.draft);
  mutate(next);
  apply(await api.put("/draft", { revision: state.revision, catalog: next.catalog, release: next.release }));
}

export async function publish(note) { apply(await api.post("/publish", { revision: state.revision, note })); }
export async function discard() { apply(await api.post("/draft/discard")); }
export async function restore(id) { apply(await api.post(`/history/${encodeURIComponent(id)}/restore`)); }

// --- helpers ----------------------------------------------------------------------------

/** Display text: Persian first (the app's primary language), then English. */
export function text(value, fallback = "") {
  if (!value) return fallback;
  if (typeof value === "string") return value;
  return value.fa || value.en || fallback;
}

export function imageUrl(path) {
  if (!path) return null;
  return path.startsWith("https://") ? path : `/${path}`;
}

export function host(url) {
  try { return new URL(url).host; } catch { return url || ""; }
}

/** Gives categories and services consecutive `order` values from their list positions. */
export function renumber(catalog) {
  catalog.categories.forEach((c, i) => { c.order = i + 1; });
  const rank = new Map(catalog.categories.map((c, i) => [c.id, i]));
  catalog.services
    .sort((a, b) => (rank.get(a.categoryId) ?? 999) - (rank.get(b.categoryId) ?? 999) || a.order - b.order)
    .forEach((s, i) => { s.order = (i + 1) * 10; });
}

export function sortedCategories(catalog) {
  return [...catalog.categories].sort((a, b) => a.order - b.order);
}

export function sortedServices(catalog) {
  return [...catalog.services].sort((a, b) => a.order - b.order);
}

/** Human-readable differences between the draft and the live version. */
export function changes() {
  if (!state.draft || !state.live) return [];
  const out = [];
  const before = state.live.catalog, after = state.draft.catalog;
  diffItems(out, "service", before.services, after.services, (s) => text(s.name, s.id));
  diffItems(out, "category", before.categories, after.categories, (c) => text(c.title, c.id));
  diffItems(out, "compare group", before.compareGroups || [], after.compareGroups || [], (g) => text(g.title, g.id));
  const order = (items) => [...items].sort((a, b) => a.order - b.order).map((i) => i.id).join();
  if (order(before.services) !== order(after.services)) out.push("Changed the order of services");
  if (order(before.categories) !== order(after.categories)) out.push("Changed the order of categories");
  for (const key of ["features", "web", "links", "refreshIntervalSeconds"]) {
    if (JSON.stringify(before[key]) !== JSON.stringify(after[key])) out.push(`Changed settings: ${key}`);
  }
  const rb = state.live.release, ra = state.draft.release;
  if (JSON.stringify(rb.default) !== JSON.stringify(ra.default)) out.push("Changed the default update rules");
  for (const channel of new Set([...Object.keys(rb.channels || {}), ...Object.keys(ra.channels || {})])) {
    if (JSON.stringify(rb.channels?.[channel]) !== JSON.stringify(ra.channels?.[channel])) out.push(`Changed the update rules for ${channel}`);
  }
  return out;
}

function diffItems(out, kind, before, after, label) {
  const old = new Map(before.map((i) => [i.id, i]));
  const now = new Map(after.map((i) => [i.id, i]));
  for (const [id, item] of now) {
    if (!old.has(id)) { out.push(`Added ${kind} “${label(item)}”`); continue; }
    const strip = ({ order, ...rest }) => JSON.stringify(rest);
    if (strip(old.get(id)) !== strip(item)) out.push(`Edited ${kind} “${label(item)}”`);
  }
  for (const [id, item] of old) if (!now.has(id)) out.push(`Removed ${kind} “${label(item)}”`);
}
