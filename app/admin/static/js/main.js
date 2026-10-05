// Shell: sign-in, navigation, the draft/publish bar and hash routing (#/services …).
import { api, ApiError, whenSignedOut } from "./api.js";
import { fill, h, icon } from "./dom.js";
import { changes, discard, loadState, publish, state, subscribe } from "./state.js";
import { confirm, dialog, showError, toast } from "./ui.js";
import * as overview from "./pages/overview.js";
import * as services from "./pages/services.js";
import * as categories from "./pages/categories.js";
import * as compare from "./pages/compare.js";
import * as releases from "./pages/releases.js";
import * as settings from "./pages/settings.js";
import * as history from "./pages/history.js";
import * as admins from "./pages/admins.js";

const PAGES = [
  ["overview", overview, "overview"],
  ["services", services, "apps"],
  ["categories", categories, "categories"],
  ["compare", compare, "compare"],
  ["releases", releases, "releases"],
  ["settings", settings, "settings"],
  ["history", history, "history"],
  ["admins", admins, "users"],
];

const app = document.getElementById("app");
let content, titleEl, draftBar, shell;

function currentPage() {
  const key = location.hash.replace(/^#\//, "") || "overview";
  return PAGES.find(([k]) => k === key) || PAGES[0];
}

// --- sign in ----------------------------------------------------------------------------

function showLogin(message) {
  const username = h("input", { class: "input", autocomplete: "username", required: true, "aria-label": "Username", placeholder: "Username" });
  const password = h("input", { class: "input", type: "password", autocomplete: "current-password", required: true, "aria-label": "Password", placeholder: "Password" });
  const error = h("div", { class: "error-text", text: message || "", hidden: !message });
  const submit = h("button", { class: "btn primary", type: "submit", text: "Sign in" });
  const form = h("form", { class: "card", on: { submit: async (event) => {
    event.preventDefault();
    submit.disabled = true;
    error.hidden = true;
    try {
      const session = await api.post("/session", { username: username.value, password: password.value });
      state.user = session.username;
      await start();
    } catch (e) {
      error.textContent = e.message;
      error.hidden = false;
      password.value = "";
      password.focus();
    } finally {
      submit.disabled = false;
    }
  } } },
    h("img", { class: "mark", src: "favicon.svg", alt: "" }),
    h("div", {}, h("h1", { text: "Daricheh Admin" }), h("div", { class: "muted", text: "Sign in to manage the app's services." })),
    username, password, error, submit);
  fill(app, h("div", { class: "login" }, form));
  username.focus();
}

whenSignedOut(() => showLogin("Your session ended. Sign in again."));

// --- shell ------------------------------------------------------------------------------

function renderShell() {
  const nav = h("nav", { class: "sidebar", "aria-label": "Sections" },
    h("div", { class: "brand" }, h("img", { src: "favicon.svg", alt: "" }), h("div", {}, "Daricheh", h("small", { text: "Admin" }))),
    PAGES.map(([key, page, iconName]) => h("a", { class: "nav-link", href: `#/${key}`, dataset: { page: key }, on: { click: () => shell.classList.remove("nav-open") } }, icon(iconName), page.title)),
    h("div", { class: "nav-spacer" }),
    h("div", { class: "account" }, h("div", { class: "avatar", text: (state.user || "?").slice(0, 1) }), h("div", { class: "grow", style: { flex: 1, minWidth: 0 } }, h("div", { class: "name", text: state.user }), h("div", { class: "hint", text: "Admin" })),
      h("button", { class: "btn ghost icon", "aria-label": "Sign out", title: "Sign out", on: { click: signOut } }, icon("logout"))));
  titleEl = h("h2", { class: "title" });
  draftBar = h("div", { class: "draft-bar" });
  content = h("div", { class: "content" });
  shell = h("div", { class: "shell" }, nav,
    h("div", { class: "main" },
      h("header", { class: "topbar" },
        h("button", { class: "btn ghost icon menu-button", "aria-label": "Menu", on: { click: () => shell.classList.toggle("nav-open") } }, icon("menu")),
        titleEl, draftBar),
      h("main", {}, content)));
  fill(app, shell);
}

function renderDraftBar() {
  const pending = changes();
  fill(draftBar, 
    h("div", { class: "status" },
      h("span", { class: "dot", style: { background: pending.length ? "var(--warning)" : "var(--success)" } }),
      h("span", { class: "status-text", text: pending.length ? `${pending.length} unpublished change${pending.length === 1 ? "" : "s"}` : "Everything is published" })),
    pending.length > 0 && h("button", { class: "btn ghost small", text: "Discard", on: { click: onDiscard } }),
    h("button", { class: "btn primary small", disabled: pending.length === 0, on: { click: onPublish } }, icon("check"), "Publish"));
}

async function renderPage() {
  const [key, page] = currentPage();
  titleEl.textContent = page.title;
  document.title = `${page.title} · Daricheh Admin`;
  for (const link of document.querySelectorAll(".nav-link")) {
    if (link.dataset.page === key) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  await page.render(content);
}

// --- actions ----------------------------------------------------------------------------

async function onPublish() {
  const pending = changes();
  const note = h("input", { class: "input", maxLength: 200, placeholder: "What changed? (optional)" });
  const ok = await dialog({
    title: "Publish to the app?",
    body: h("div", { class: "stack" },
      h("p", { class: "muted", style: { margin: 0 }, text: "Users get these changes the next time they open the app." }),
      h("ul", { class: "changes" }, pending.map((c) => h("li", { text: c }))),
      note),
    actions: (close) => [h("button", { class: "btn", text: "Cancel", on: { click: () => close(false) } }), h("button", { class: "btn primary", text: "Publish", on: { click: () => close(true) } })],
  });
  if (!ok) return;
  try {
    await publish(note.value.trim());
    toast("Published — live now");
  } catch (error) {
    if (error instanceof ApiError && error.problems.length) showError(`${error.message}: ${error.problems.map((p) => `${p.path} ${p.message}`).join("; ")}`);
    else showError(error);
  }
}

async function onDiscard() {
  if (!(await confirm({ title: "Discard all unpublished changes?", message: "The draft goes back to the live version. This can't be undone.", confirmLabel: "Discard", danger: true }))) return;
  try { await discard(); toast("Draft discarded"); } catch (error) { showError(error); }
}

async function signOut() {
  try { await api.del("/session"); } catch { /* signed out anyway */ }
  state.user = null;
  showLogin();
}

// --- start ------------------------------------------------------------------------------

let started = false;
async function start() {
  await loadState();
  renderShell();
  renderDraftBar();
  await renderPage();
  if (!started) {
    started = true;
    window.addEventListener("hashchange", () => renderPage().catch(showError));
    subscribe(() => {
      renderDraftBar();
      // History and Admins load their own data; the others re-render from the draft.
      const [key] = currentPage();
      if (key !== "history" && key !== "admins") renderPage().catch(showError);
    });
    // Another admin may publish meanwhile: refresh when the tab comes back.
    document.addEventListener("visibilitychange", () => { if (!document.hidden && state.user) loadState().catch(() => {}); });
  }
}

(async () => {
  try {
    const session = await api.get("/session");
    state.user = session.username;
    await start();
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) showLogin();
    else fill(app, h("div", { class: "login" }, h("div", { class: "card", text: `Can't load the dashboard: ${error.message}` })));
  }
})();
