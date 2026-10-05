// Admins: who can sign in to this dashboard, and your own password.
import { api } from "../api.js";
import { fill, h, icon } from "../dom.js";
import { state } from "../state.js";
import { confirm, section, showError, textField, toast } from "../ui.js";

export const title = "Admins";

function strongPassword() {
  const bytes = crypto.getRandomValues(new Uint8Array(15));
  return btoa(String.fromCharCode(...bytes)).replace(/[+/=]/g, "").slice(0, 18);
}

export async function render(root) {
  let admins;
  try { admins = await api.get("/admins"); } catch (error) { showError(error); return; }

  const username = textField({ label: "Username", placeholder: "sara", mono: true, hint: "3–32 lowercase letters, digits, '.', '-' or '_'." });
  const password = textField({ label: "Password", mono: true, hint: "At least 10 characters. Share it privately; they can change it after signing in." });
  const generate = h("button", { class: "btn small", type: "button", text: "Generate", on: { click: () => { password.value = strongPassword(); } } });
  const add = h("button", { class: "btn primary", text: "Add admin" });
  add.addEventListener("click", async () => {
    try {
      await api.post("/admins", { username: username.value, password: password.value });
      toast(`${username.value} can now sign in`);
      render(root);
    } catch (error) { showError(error); }
  });

  const current = textField({ label: "Current password", type: "password" });
  const next = textField({ label: "New password", type: "password", hint: "At least 10 characters. Signs you out everywhere else." });
  const change = h("button", { class: "btn primary", text: "Change password" });
  change.addEventListener("click", async () => {
    try {
      await api.post("/password", { current: current.input.value, new: next.input.value });
      current.value = ""; next.value = "";
      toast("Password changed");
    } catch (error) { showError(error); }
  });

  fill(root, 
    h("div", { class: "page-head" }, h("div", { class: "grow" }, h("h1", { text: "Admins" }), h("div", { class: "muted", text: "Everyone here can edit and publish." }))),
    h("div", { class: "stack" },
      h("div", { class: "card" }, h("table", { class: "table" },
        h("thead", {}, h("tr", {}, ["Username", "Added", "By", ""].map((t) => h("th", { text: t })))),
        h("tbody", {}, admins.map((a) => h("tr", {},
          h("td", {}, h("span", { class: "mono", text: a.username }), a.username === state.user && [" ", h("span", { class: "chip accent", text: "You" })]),
          h("td", { class: "muted", text: new Date(a.createdAt * 1000).toLocaleDateString() }),
          h("td", { class: "muted", text: a.createdBy || "—" }),
          h("td", { style: { textAlign: "end" } }, a.username !== state.user && h("button", { class: "btn ghost icon danger", "aria-label": `Remove ${a.username}`, on: { click: async () => {
            if (!(await confirm({ title: `Remove ${a.username}?`, message: "They can no longer sign in.", confirmLabel: "Remove", danger: true }))) return;
            try { await api.del(`/admins/${encodeURIComponent(a.username)}`); toast("Removed"); render(root); } catch (error) { showError(error); }
          } } }, icon("trash")))))))),
      section("Add an admin", h("div", { class: "grid-2" }, username.el, h("div", { class: "field" }, password.el, h("div", {}, generate))), h("div", { class: "row", style: { justifyContent: "flex-end" } }, add)),
      section("Your password", h("div", { class: "grid-2" }, current.el, next.el), h("div", { class: "row", style: { justifyContent: "flex-end" } }, change))));
}
