// Compare groups: services that answer the same need (Snapp, Tapsi). The app suggests them
// side by side and lets users switch between them in one tap.
import { fill, h, icon } from "../dom.js";
import { commit, imageUrl, sortedServices, state, text } from "../state.js";
import { applyProblems, confirm, drawer, localizedField, section, showError, textField, toast } from "../ui.js";

export const title = "Compare groups";

export function render(root) {
  const { catalog } = state.draft;
  const groups = catalog.compareGroups || [];
  const byId = new Map(catalog.services.map((s) => [s.id, s]));
  fill(root, 
    h("div", { class: "page-head" },
      h("div", { class: "grow" }, h("h1", { text: "Compare groups" }), h("div", { class: "muted", text: "Services worth comparing and switching between. Each group needs at least two." })),
      h("button", { class: "btn primary", on: { click: () => edit(null) } }, icon("plus"), "Add group")),
    groups.length
      ? h("ul", { class: "list card" }, groups.map((g) => h("li", { class: "item" },
          h("div", { class: "grow" }, h("div", { class: "name", text: text(g.title, g.id) }), h("div", { class: "sub ltr", text: g.id })),
          h("div", { class: "row", style: { gap: "4px" } }, g.serviceIds.map((id) => {
            const s = byId.get(id);
            return s?.logo ? h("img", { class: "logo", src: imageUrl(s.logo), alt: text(s.name, id), title: text(s.name, id), style: { width: "30px", height: "30px" } }) : h("span", { class: "chip", text: id });
          })),
          h("button", { class: "btn ghost icon", "aria-label": "Edit", on: { click: () => edit(g.id) } }, icon("edit")),
          h("button", { class: "btn ghost icon danger", "aria-label": "Delete", on: { click: () => remove(g.id) } }, icon("trash")))))
      : h("div", { class: "card empty", text: "No compare groups yet." }));
}

async function remove(id) {
  if (!(await confirm({ title: "Delete this group?", message: "The services stay; only the comparison goes.", confirmLabel: "Delete", danger: true }))) return;
  try {
    await commit((d) => { d.catalog.compareGroups = d.catalog.compareGroups.filter((g) => g.id !== id); });
    toast("Deleted — in draft");
  } catch (error) { showError(error); }
}

function edit(id) {
  const { catalog } = state.draft;
  const existing = id ? catalog.compareGroups.find((g) => g.id === id) : null;
  const selected = new Set(existing?.serviceIds || []);
  const f = {
    title: localizedField({ label: "Title", value: existing?.title, maxLength: 64, hint: "e.g. “Ride hailing”." }),
    id: textField({ label: "ID", value: existing?.id, mono: true, disabled: Boolean(existing), placeholder: "rides" }),
  };
  const filter = h("input", { class: "input", type: "search", placeholder: "Filter services" });
  const list = h("div", { class: "check-list" });
  const draw = () => {
    const q = filter.value.trim().toLowerCase();
    fill(list, ...sortedServices(catalog)
      .filter((s) => !q || `${s.id} ${s.name?.fa || ""} ${s.name?.en || ""}`.toLowerCase().includes(q))
      .map((s) => {
        const box = h("input", { type: "checkbox", checked: selected.has(s.id) });
        box.addEventListener("change", () => (box.checked ? selected.add(s.id) : selected.delete(s.id)));
        return h("label", {}, box, s.logo ? h("img", { src: imageUrl(s.logo), alt: "" }) : null, h("span", { text: text(s.name, s.id) }), h("span", { class: "muted small ltr", text: s.id }));
      }));
  };
  filter.addEventListener("input", draw);
  draw();
  const members = { setError: (m) => { list.style.borderColor = m ? "var(--danger)" : ""; } };
  let index = -1;
  drawer({
    title: existing ? `Edit ${text(existing.title, existing.id)}` : "Add a compare group",
    body: [section("Group", f.title.el, f.id.el), section("Services", filter, list)],
    onProblems: (problems) => applyProblems(problems, `catalog.compareGroups[${index}]`, { ...f, serviceIds: members }),
    onSave: async () => {
      const groupId = existing ? existing.id : f.id.value;
      // Keep the catalog's order, so the app lists them as on Home.
      const serviceIds = sortedServices(catalog).map((s) => s.id).filter((sid) => selected.has(sid));
      if (serviceIds.length < 2) { members.setError(true); throw new Error("Pick at least two services"); }
      const next = { ...(existing || {}), id: groupId, title: f.title.value, serviceIds };
      await commit((d) => {
        d.catalog.compareGroups = d.catalog.compareGroups || [];
        if (existing) d.catalog.compareGroups[d.catalog.compareGroups.findIndex((g) => g.id === existing.id)] = next;
        else d.catalog.compareGroups.push(next);
        index = d.catalog.compareGroups.findIndex((g) => g.id === groupId);
      });
      toast("Saved to draft");
    },
  });
}
