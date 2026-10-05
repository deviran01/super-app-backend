// The dashboard's view of the draft. Pages read `state.draft` and change it only through
// commit(), which saves the whole draft to the server (validated there, with the revision
// the change was based on, so two admins can't silently overwrite each other).
import { api, ApiError } from "./api.js";

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

/**
 * Reloads the draft. `quiet` (tab came back into view): pages re-render only when something
 * actually changed on the server, so unsaved form input isn't wiped for nothing.
 */
export async function loadState({ quiet = false } = {}) {
  const response = await api.get("/state");
  if (quiet && response.revision === state.revision && response.published?.id === state.published?.id) return;
  apply(response);
}

let pinnedRevision = null;
let queue = Promise.resolve();

/**
 * Runs `save` with commits based on `revision` (when a form was opened): if another admin
 * changed the draft since, the save is refused instead of overwriting their change.
 */
export async function withRevision(revision, save) {
  pinnedRevision = revision;
  try { return await save(); } finally { pinnedRevision = null; }
}

/**
 * Applies `mutate` to a copy of the draft and saves it. Throws ApiError with `problems`.
 * Commits run one after another, each on the draft the previous one produced, so quick
 * successive edits (two switches, two drags) don't collide with each other.
 */
export function commit(mutate) {
  const base = pinnedRevision;
  const run = queue.then(() => save(mutate, base));
  queue = run.catch(() => {});
  return run;
}

async function save(mutate, base) {
  const next = structuredClone(state.draft);
  mutate(next);
  await conflictAware(() => api.put("/draft", { revision: base ?? state.revision, catalog: next.catalog, release: next.release }));
}

/** On a 409 the draft is reloaded, so the page shows what the other admin saved. */
async function conflictAware(request) {
  try {
    apply(await request());
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 409) throw error;
    await loadState().catch(() => {});
    throw new ApiError(409, "Another admin changed the draft meanwhile. It has been reloaded; open the form again and redo your change.");
  }
}

export async function publish(note) { await conflictAware(() => api.post("/publish", { revision: state.revision, note })); }
export async function discard() { await conflictAware(() => api.post("/draft/discard", { revision: state.revision })); }
export async function restore(id) { await conflictAware(() => api.post(`/history/${encodeURIComponent(id)}/restore`, { revision: state.revision })); }

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
