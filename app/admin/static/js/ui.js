// Reusable UI: toasts, dialogs, the editing drawer, form fields and sortable lists.
import { api, ApiError } from "./api.js";
import { append, clear, h, icon } from "./dom.js";
import { imageUrl } from "./state.js";

// --- feedback ---------------------------------------------------------------------------

export function toast(message, kind = "info") {
  const el = h("div", { class: `toast ${kind}`, text: message });
  document.getElementById("toasts").append(el);
  setTimeout(() => el.remove(), kind === "error" ? 6000 : 3000);
}

export function showError(error) {
  toast(error instanceof ApiError || error instanceof Error ? error.message : String(error), "error");
}

function overlay(node, onClose, scrimClass = "scrim") {
  const scrim = h("div", { class: scrimClass, on: { click: () => onClose() } });
  const keys = (event) => { if (event.key === "Escape") onClose(); };
  document.addEventListener("keydown", keys);
  document.body.append(scrim, node);
  return () => { document.removeEventListener("keydown", keys); scrim.remove(); node.remove(); };
}

export function dialog({ title, body, actions }) {
  return new Promise((resolve) => {
    let remove;
    const close = (value) => { remove(); resolve(value); };
    const node = h("div", { class: "dialog", role: "dialog", "aria-modal": "true", "aria-label": title },
      h("h2", { text: title }),
      body,
      h("div", { class: "actions" }, actions(close)));
    remove = overlay(node, () => close(undefined), "scrim top");
    node.querySelector("input, textarea, button.primary, button")?.focus();
  });
}

export function confirm({ title, message, confirmLabel = "Confirm", danger = false }) {
  return dialog({
    title,
    body: h("p", { class: "muted", text: message, style: { margin: 0 } }),
    actions: (close) => [
      h("button", { class: "btn", text: "Cancel", on: { click: () => close(false) } }),
      h("button", { class: `btn primary ${danger ? "danger solid" : ""}`, text: confirmLabel, on: { click: () => close(true) } }),
    ],
  }).then(Boolean);
}

/**
 * A side drawer holding an editing form. `onSave` may throw an ApiError: its problems are
 * listed on top and passed to `onProblems` so fields can highlight themselves.
 */
export function drawer({ title, subtitle, body, onSave, saveLabel = "Save to draft", footerStart, onProblems }) {
  const problems = h("div");
  const save = h("button", { class: "btn primary", text: saveLabel });
  let remove;
  const close = () => remove();
  save.addEventListener("click", async () => {
    clear(problems);
    save.disabled = true;
    try {
      await onSave();
      close();
    } catch (error) {
      if (error instanceof ApiError && error.problems.length) {
        problems.append(h("ul", { class: "problems" }, error.problems.map((p) => h("li", { text: `${p.path}: ${p.message}` }))));
        onProblems?.(error.problems);
        problems.scrollIntoView({ block: "nearest" });
      } else {
        showError(error);
      }
    } finally {
      save.disabled = false;
    }
  });
  const node = h("aside", { class: "drawer", role: "dialog", "aria-modal": "true", "aria-label": title },
    h("div", { class: "drawer-head" },
      h("div", { class: "grow" }, h("h2", { text: title }), subtitle && h("div", { class: "muted small", text: subtitle })),
      h("button", { class: "btn ghost icon", "aria-label": "Close", on: { click: close } }, icon("close"))),
    h("div", { class: "drawer-body" }, problems, body),
    h("div", { class: "drawer-foot" }, footerStart && h("div", { style: { marginInlineEnd: "auto" } }, footerStart),
      h("button", { class: "btn", text: "Cancel", on: { click: close } }), save));
  remove = overlay(node, close);
  node.querySelector("input:not([type=checkbox]):not([disabled]), textarea, select")?.focus();
  return { close };
}

// --- fields -----------------------------------------------------------------------------

function wrap(label, control, hint) {
  const error = h("div", { class: "error-text", hidden: true });
  const el = h("div", { class: "field" }, label && h("label", { text: label }), control, hint && h("div", { class: "hint", text: hint }), error);
  return {
    el,
    setError(message) {
      error.hidden = !message;
      error.textContent = message || "";
      for (const input of el.querySelectorAll(".input")) input.classList.toggle("invalid", Boolean(message));
    },
  };
}

export function textField({ label, value = "", placeholder = "", hint, type = "text", dir, mono, disabled, maxLength }) {
  const input = h("input", { class: `input ${mono ? "mono" : ""}`, type, value: value ?? "", placeholder, dir, disabled, maxLength });
  const field = wrap(label, input, hint);
  return { ...field, input, get value() { return input.value.trim(); }, set value(v) { input.value = v ?? ""; } };
}

export function numberField({ label, value, min = 0, hint, placeholder }) {
  const input = h("input", { class: "input", type: "number", min, step: 1, value: value ?? "", placeholder });
  const field = wrap(label, input, hint);
  return { ...field, input, get value() { return input.value === "" ? null : Number(input.value); } };
}

/** Persian and English side by side; the value is {fa, en} or null when both are empty. */
export function localizedField({ label, value, maxLength = 64, multiline = false, hint }) {
  const make = (lang) => {
    const props = { class: "input", maxLength, dir: lang === "fa" ? "rtl" : "ltr", lang, placeholder: lang === "fa" ? "فارسی" : "English" };
    const input = multiline ? h("textarea", props) : h("input", { ...props, type: "text" });
    input.value = (typeof value === "string" ? (lang === "en" ? value : "") : value?.[lang]) || "";
    return input;
  };
  const fa = make("fa"), en = make("en");
  const field = wrap(label, h("div", { class: "grid-2" }, fa, en), hint);
  return {
    ...field,
    get value() {
      const out = {};
      if (fa.value.trim()) out.fa = fa.value.trim();
      if (en.value.trim()) out.en = en.value.trim();
      return Object.keys(out).length ? out : null;
    },
  };
}

export function toggleField({ label, checked = false, hint }) {
  const input = h("input", { type: "checkbox", checked: Boolean(checked) });
  const el = h("label", { class: "switch" }, input, h("span", { class: "track" }), h("span", {}, h("span", { class: "label", text: label }), hint && h("div", { class: "hint", text: hint })));
  return { el, input, setError() {}, get value() { return input.checked; } };
}

export function selectField({ label, value, options, hint }) {
  const select = h("select", { class: "input" }, options.map((o) => h("option", { value: o.value, text: o.label, selected: o.value === value })));
  const field = wrap(label, select, hint);
  return { ...field, input: select, get value() { return select.value; } };
}

/** One entry per line (domains, schemes). */
export function linesField({ label, values = [], hint, placeholder }) {
  const area = h("textarea", { class: "input mono", placeholder, dir: "ltr" });
  area.value = (values || []).join("\n");
  const field = wrap(label, area, hint);
  return { ...field, get value() { return area.value.split(/[\n,]+/).map((v) => v.trim()).filter(Boolean); } };
}

export function colorField({ label, value, hint }) {
  const picker = h("input", { type: "color", value: value || "#3354E6", style: { width: "44px", height: "38px", padding: "2px", border: "1px solid var(--border)", borderRadius: "8px", background: "var(--surface)" } });
  const text = h("input", { class: "input mono", value: value || "", placeholder: "#3354E6", maxLength: 7, dir: "ltr" });
  picker.addEventListener("input", () => { text.value = picker.value.toUpperCase(); });
  text.addEventListener("input", () => { if (/^#[0-9a-f]{6}$/i.test(text.value)) picker.value = text.value; });
  const field = wrap(label, h("div", { class: "row" }, picker, text), hint);
  return { ...field, get value() { return text.value.trim() ? text.value.trim().toUpperCase() : null; } };
}

/**
 * Upload (or fetch from Cafe Bazaar) a logo or category icon. The server normalizes the
 * image and names it after its content; `getName` supplies the id used in the file name.
 */
export function imageField({ label, kind, value, getName, hint, tint }) {
  let current = value || null;
  const preview = h("img", { class: `preview ${kind === "icon" ? "icon" : ""}`, alt: "" });
  if (tint) preview.style.background = tint;
  const file = h("input", { type: "file", accept: "image/png,image/jpeg,image/webp", hidden: true });
  const status = h("div", { class: "hint" });
  const render = () => {
    preview.src = imageUrl(current) || "data:image/gif;base64,R0lGODlhAQABAAAAACw=";
    remove.hidden = !current;
    status.textContent = current || "No image yet";
  };
  const name = () => {
    const id = getName();
    if (!/^[a-z0-9][a-z0-9_-]{0,63}$/.test(id || "")) throw new Error("Set a valid id first");
    return id;
  };
  const run = async (task) => {
    status.textContent = "Uploading…";
    try { current = (await task()).path; } catch (error) { showError(error); }
    render();
  };
  file.addEventListener("change", () => {
    const chosen = file.files[0];
    file.value = "";
    if (chosen) run(() => api.upload(`/images/${kind}?name=${encodeURIComponent(name())}`, chosen));
  });
  const upload = h("button", { class: "btn small", type: "button", on: { click: () => file.click() } }, icon("upload"), "Upload");
  const remove = h("button", { class: "btn small ghost danger", type: "button", text: "Remove", on: { click: () => { current = null; render(); } } });
  const fromStore = kind === "logo" && h("button", {
    class: "btn small", type: "button",
    on: {
      click: async () => {
        const pkg = textField({ label: "Android package name", placeholder: "cab.snapp.passenger", mono: true, hint: "Its official app icon is taken from its Cafe Bazaar listing." });
        const ok = await dialog({
          title: "Logo from Cafe Bazaar",
          body: pkg.el,
          actions: (close) => [h("button", { class: "btn", text: "Cancel", on: { click: () => close(false) } }), h("button", { class: "btn primary", text: "Fetch", on: { click: () => close(true) } })],
        });
        if (ok && pkg.value) run(() => api.post("/images/logo/from-store", { name: name(), package: pkg.value }));
      },
    },
  }, icon("store"), "From Cafe Bazaar");
  const field = wrap(label, h("div", { class: "image-picker" }, preview, h("div", { class: "stack", style: { gap: "6px" } }, h("div", { class: "actions" }, upload, fromStore, remove), status), file), hint);
  render();
  return { ...field, get value() { return current; } };
}

/** Maps server problems under `prefix` (e.g. "catalog.services[3]") onto fields by name. */
export function applyProblems(problems, prefix, fields) {
  for (const field of Object.values(fields)) field.setError?.(null);
  for (const problem of problems) {
    if (!problem.path.startsWith(prefix)) continue;
    const key = problem.path.slice(prefix.length).replace(/^\./, "").split(/[.[]/)[0];
    fields[key]?.setError?.(problem.message);
  }
}

// --- sortable lists ---------------------------------------------------------------------

/**
 * Drag rows by their `.handle` (mouse, touch or pen) or move them with the arrow keys while
 * the handle has focus. Calls `onReorder(ids)` with the new order of `[data-id]` rows.
 */
export function sortable(list, onReorder) {
  const ids = () => [...list.children].map((row) => row.dataset.id);
  list.addEventListener("keydown", (event) => {
    const handle = event.target.closest?.(".handle");
    if (!handle || (event.key !== "ArrowUp" && event.key !== "ArrowDown")) return;
    event.preventDefault();
    const row = handle.closest("[data-id]");
    const sibling = event.key === "ArrowUp" ? row.previousElementSibling : row.nextElementSibling;
    if (!sibling) return;
    if (event.key === "ArrowUp") sibling.before(row); else sibling.after(row);
    handle.focus();
    onReorder(ids());
  });
  list.addEventListener("pointerdown", (event) => {
    const handle = event.target.closest?.(".handle");
    if (!handle || handle.disabled || event.button !== 0) return;
    event.preventDefault();
    const row = handle.closest("[data-id]");
    const before = ids().join();
    const startY = event.clientY;
    const placeholder = h("li", { class: "item placeholder", style: { height: `${row.offsetHeight}px` } });
    const rect = row.getBoundingClientRect();
    row.classList.add("dragging");
    row.style.width = `${rect.width}px`;
    row.after(placeholder);
    handle.setPointerCapture(event.pointerId);
    const move = (e) => {
      row.style.transform = `translateY(${e.clientY - startY}px)`;
      const target = [...list.children].find((child) => {
        if (child === row || child === placeholder) return false;
        const box = child.getBoundingClientRect();
        return e.clientY < box.top + box.height / 2;
      });
      if (target) target.before(placeholder); else list.append(placeholder);
    };
    const end = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", end);
      handle.removeEventListener("pointercancel", end);
      placeholder.replaceWith(row);
      row.classList.remove("dragging");
      row.style.transform = "";
      row.style.width = "";
      if (ids().join() !== before) onReorder(ids());
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", end);
    handle.addEventListener("pointercancel", end);
  });
}

export function dragHandle(label, disabled = false) {
  return h("button", { class: "handle", type: "button", "aria-label": `Reorder ${label} (arrow keys)`, title: "Drag to reorder", disabled }, icon("grip"));
}

export function section(title, ...children) {
  return h("section", { class: "card section" }, h("h3", { text: title }), children);
}

export function advanced(title, ...children) {
  return h("details", { class: "card section" }, h("summary", { text: title }), children);
}

export { append, clear };
