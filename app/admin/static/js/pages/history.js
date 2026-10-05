// History: every published version; any of them can be loaded back into the draft.
import { api } from "../api.js";
import { fill, h } from "../dom.js";
import { restore, state } from "../state.js";
import { confirm, showError, toast } from "../ui.js";

export const title = "History";

export async function render(root) {
  fill(root, h("div", { class: "muted", text: "Loading…" }));
  let entries;
  try { entries = await api.get("/history"); } catch (error) { showError(error); return; }
  fill(root, 
    h("div", { class: "page-head" }, h("div", { class: "grow" }, h("h1", { text: "History" }), h("div", { class: "muted", text: "Every published version. Restoring loads it into the draft; nothing changes for users until you publish." }))),
    h("div", { class: "card" }, h("table", { class: "table" },
      h("thead", {}, h("tr", {}, ["Published", "By", "Note", "Services", ""].map((t) => h("th", { text: t })))),
      h("tbody", {}, entries.map((e, i) => h("tr", {},
        h("td", {}, new Date(e.publishedAt * 1000).toLocaleString(), i === 0 && [" ", h("span", { class: "chip success", text: "Live" })]),
        h("td", { text: e.publishedBy }),
        h("td", { class: "muted", text: e.note || "—" }),
        h("td", { text: `${e.summary?.enabled ?? "?"} / ${e.summary?.services ?? "?"}` }),
        h("td", { style: { textAlign: "end" } }, h("button", { class: "btn small", text: "Restore to draft", on: { click: () => restoreEntry(e) } }))))))));
}

async function restoreEntry(entry) {
  const ok = await confirm({
    title: "Load this version into the draft?",
    message: `${state.dirty ? "Your unpublished changes are replaced. " : ""}Publish afterwards to make it live.`,
    confirmLabel: "Restore",
    danger: state.dirty,
  });
  if (!ok) return;
  try {
    await restore(entry.id);
    toast("Restored into the draft — review and publish");
    location.hash = "#/services";
  } catch (error) { showError(error); }
}
