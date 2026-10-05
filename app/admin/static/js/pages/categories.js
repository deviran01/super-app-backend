// Categories: the sections services are grouped in, in display order.
import { fill, h, icon } from "../dom.js";
import { commit, imageUrl, renumber, sortedCategories, state, text } from "../state.js";
import { applyProblems, colorField, confirm, dialog, dragHandle, drawer, imageField, localizedField, section, selectField, showError, sortable, textField, toast, toggleField } from "../ui.js";

export const title = "Categories";

export function render(root) {
  const { catalog } = state.draft;
  const categories = sortedCategories(catalog);
  const count = (id) => catalog.services.filter((s) => s.categoryId === id).length;
  const list = h("ul", { class: "list card" }, categories.map((c) => row(c, count(c.id))));
  sortable(list, reorder);
  fill(root, 
    h("div", { class: "page-head" },
      h("div", { class: "grow" }, h("h1", { text: "Categories" }), h("div", { class: "muted", text: "Drag to change the order of sections in the app. Categories without enabled services are hidden automatically." })),
      h("button", { class: "btn primary", on: { click: () => edit(null) } }, icon("plus"), "Add category")),
    categories.length ? list : h("div", { class: "card empty", text: "No categories yet." }));
}

export function glyph(category) {
  const color = category.color || "var(--accent)";
  const src = imageUrl(category.icon);
  // Icons are white glyphs that the app tints; tint them the same way here.
  const mask = src && `url("${encodeURI(src)}") center / contain no-repeat`;
  return h("div", { class: "glyph", style: { background: `color-mix(in srgb, ${color} 16%, transparent)`, color } },
    src ? h("span", { style: { width: "24px", height: "24px", background: color, mask, webkitMask: mask } }) : icon("apps"));
}

function row(category, services) {
  const off = category.enabled === false;
  const toggle = h("input", { type: "checkbox", checked: !off, "aria-label": `${text(category.title)} enabled` });
  toggle.addEventListener("change", async () => {
    try {
      await commit((d) => { d.catalog.categories.find((c) => c.id === category.id).enabled = toggle.checked; });
      toast("Saved to draft");
    } catch (error) { showError(error); }
  });
  return h("li", { class: `item ${off ? "disabled" : ""}`, dataset: { id: category.id } },
    dragHandle(text(category.title, category.id)),
    glyph(category),
    h("div", { class: "grow" },
      h("div", { class: "row", style: { gap: "8px" } }, h("span", { class: "name", text: text(category.title, category.id) }),
        category.title?.en && category.title?.fa && h("span", { class: "muted small", text: category.title.en })),
      h("div", { class: "sub ltr", text: `${category.id} · ${services} service${services === 1 ? "" : "s"}` })),
    h("label", { class: "switch", title: off ? "Hidden" : "Shown" }, toggle, h("span", { class: "track" })),
    h("button", { class: "btn ghost icon", "aria-label": `Edit ${text(category.title)}`, on: { click: () => edit(category.id) } }, icon("edit")),
    h("button", { class: "btn ghost icon danger", "aria-label": `Delete ${text(category.title)}`, on: { click: () => remove(category.id) } }, icon("trash")));
}

async function reorder(ids) {
  try {
    await commit((d) => {
      ids.forEach((id, i) => { d.catalog.categories.find((c) => c.id === id).order = i; });
      d.catalog.categories.sort((a, b) => a.order - b.order);
      renumber(d.catalog);
    });
  } catch (error) { showError(error); }
}

async function remove(id) {
  const { catalog } = state.draft;
  const category = catalog.categories.find((c) => c.id === id);
  const services = catalog.services.filter((s) => s.categoryId === id);
  let moveTo = null;
  if (services.length) {
    const others = sortedCategories(catalog).filter((c) => c.id !== id);
    if (!others.length) return showError("Add another category first: its services need a new home.");
    const target = selectField({ label: "Move its services to", value: others[0].id, options: others.map((c) => ({ value: c.id, label: text(c.title, c.id) })) });
    const ok = await dialog({
      title: `Delete “${text(category.title, id)}”?`,
      body: h("div", { class: "stack" }, h("p", { class: "muted", style: { margin: 0 }, text: `It has ${services.length} service(s). They move to another category.` }), target.el),
      actions: (close) => [h("button", { class: "btn", text: "Cancel", on: { click: () => close(false) } }), h("button", { class: "btn danger solid", text: "Delete and move", on: { click: () => close(true) } })],
    });
    if (!ok) return;
    moveTo = target.value;
  } else if (!(await confirm({ title: `Delete “${text(category.title, id)}”?`, message: "It has no services.", confirmLabel: "Delete", danger: true }))) {
    return;
  }
  try {
    await commit((d) => {
      d.catalog.categories = d.catalog.categories.filter((c) => c.id !== id);
      for (const s of d.catalog.services) if (s.categoryId === id) { s.categoryId = moveTo; s.order = 1_000_000 + s.order; }
      renumber(d.catalog);
    });
    toast("Deleted — in draft");
  } catch (error) { showError(error); }
}

function edit(id) {
  const { catalog } = state.draft;
  const existing = id ? catalog.categories.find((c) => c.id === id) : null;
  const c = existing || { enabled: true };
  const f = {
    title: localizedField({ label: "Title", value: c.title, maxLength: 64 }),
    id: textField({ label: "ID", value: c.id, mono: true, disabled: Boolean(existing), placeholder: "transport", hint: existing ? "Can't change: services refer to it." : "Lowercase letters, digits, - or _." }),
    color: colorField({ label: "Accent color", value: c.color, hint: "Tints the icon and the category's highlights." }),
    enabled: toggleField({ label: "Shown", checked: c.enabled !== false }),
  };
  f.icon = imageField({ label: "Icon", kind: "icon", value: c.icon, tint: c.color || "var(--accent)", getName: () => existing?.id || f.id.value,
    hint: "A single-color glyph (transparent PNG, or dark on white). The app tints it." });
  let index = -1;
  drawer({
    title: existing ? `Edit ${text(c.title, c.id)}` : "Add a category",
    body: [section("Category", f.title.el, f.id.el, f.icon.el, f.color.el, f.enabled.el)],
    onProblems: (problems) => applyProblems(problems, `catalog.categories[${index}]`, f),
    onSave: async () => {
      const categoryId = existing ? existing.id : f.id.value;
      if (!existing && catalog.categories.some((x) => x.id === categoryId)) {
        f.id.setError("Another category already uses this ID");
        throw new Error("Choose another ID");
      }
      const next = { ...(existing || {}), id: categoryId, title: f.title.value, icon: f.icon.value, color: f.color.value, enabled: f.enabled.value };
      await commit((d) => {
        if (existing) d.catalog.categories[d.catalog.categories.findIndex((x) => x.id === existing.id)] = next;
        else { next.order = 1_000_000; d.catalog.categories.push(next); }
        d.catalog.categories.sort((a, b) => a.order - b.order);
        renumber(d.catalog);
        index = d.catalog.categories.findIndex((x) => x.id === categoryId);
      });
      toast(existing ? "Saved to draft" : "Added to draft");
    },
  });
}
