// Feedback: anonymous messages sent from the app's Settings (see app/feedback.py). Loads its
// own data; the draft doesn't affect it. Counts go out as a "feedback-counts" event for the
// unread badge in the sidebar.
import { api } from "../api.js";
import { fill, h, icon } from "../dom.js";
import { confirm, showError, toast } from "../ui.js";

export const title = "Feedback";

const FOLDERS = [["inbox", "Inbox"], ["archived", "Archived"], ["spam", "Spam"]];
const KINDS = { problem: ["Problem", "warning"], idea: ["Idea", "accent"], other: ["Other", ""] };
const CHANNELS = { bazaar: "Cafe Bazaar", myket: "Myket", direct: "Direct", other: "Other store" };
// Android API level → version, for the API levels the app supports (minSdk 26).
const ANDROID = { 26: "8.0", 27: "8.1", 28: "9", 29: "10", 30: "11", 31: "12", 32: "12L", 33: "13", 34: "14", 35: "15", 36: "16", 37: "17" };
const EMPTY = {
  inbox: "No messages yet. Feedback sent from the app's Settings shows up here.",
  archived: "Nothing archived.",
  spam: "Nothing here. Move messages you don't want in the inbox here; empty it anytime.",
};
const PAGE = 30;

const view = { folder: "inbox" };
let latest = 0;

export async function render(root) {
  const request = ++latest;
  const folder = view.folder;
  let page;
  try {
    page = await api.get(`/feedback?folder=${folder}&limit=${PAGE}`);
  } catch (error) {
    showError(error);
    return;
  }
  // Another folder was picked while this one loaded.
  if (request !== latest) return;
  publishCounts(page.counts);
  const list = h("div", { class: "stack messages" });
  const more = h("div");
  const rerender = () => render(root);

  const append = (items, next) => {
    for (const item of items) list.append(message(item, folder, rerender));
    fill(more, next && h("button", {
      class: "btn", text: "Show older",
      on: { click: async (event) => {
        event.target.disabled = true;
        try {
          const older = await api.get(`/feedback?folder=${folder}&limit=${PAGE}&before=${next}`);
          append(older.items, older.next);
        } catch (error) {
          showError(error);
          event.target.disabled = false;
        }
      } },
    }));
  };
  append(page.items, page.next);

  fill(root,
    head(page.counts, rerender),
    page.items.length === 0
      ? h("div", { class: "card empty", text: EMPTY[folder] })
      : h("div", { class: "stack" }, list, more),
    h("p", { class: "hint", text: "Messages are anonymous: only the text, its kind and the app build (store, version, Android version) are stored — no account, device or address. Only floods are limited (per address and in total); repeats of the same text are counted on the first copy, and messages are deleted after a year." }));
}

function head(counts, rerender) {
  const tabs = h("div", { class: "seg", role: "group", "aria-label": "Folder" },
    FOLDERS.map(([key, label]) => {
      const n = key === "inbox" ? counts.unread : counts[key];
      return h("button", {
        class: "btn small", "aria-pressed": String(view.folder === key),
        on: { click: () => { view.folder = key; rerender(); } },
      }, label, n > 0 && h("span", { class: `count ${key === "inbox" ? "accent" : ""}`, text: String(n) }));
    }));
  const bulk = view.folder === "inbox" && counts.unread > 0
    ? h("button", { class: "btn", on: { click: () => bulkAction("/feedback/read-all", "Marked as read", rerender) } }, icon("check"), "Mark all read")
    : view.folder === "spam" && counts.spam > 0
      ? h("button", { class: "btn danger", on: { click: async () => {
        if (await confirm({ title: `Delete ${counts.spam} spam message${counts.spam === 1 ? "" : "s"}?`, message: "They're deleted for good.", confirmLabel: "Empty spam", danger: true })) {
          bulkAction("/feedback/empty-spam", "Spam emptied", rerender);
        }
      } } }, icon("trash"), "Empty spam")
      : null;
  return h("div", { class: "page-head" },
    h("div", { class: "grow" }, h("h1", { text: "Feedback" }), h("div", { class: "muted", text: "What users tell you from the app, newest first." })),
    tabs, bulk,
    h("button", { class: "btn icon", "aria-label": "Refresh", title: "Refresh", on: { click: rerender } }, icon("refresh")));
}

async function bulkAction(path, done, rerender) {
  try {
    await api.post(path);
    toast(done);
  } catch (error) {
    showError(error);
  }
  rerender();
}

function message(item, folder, rerender) {
  const [kindLabel, kindTone] = KINDS[item.kind] || KINDS.other;
  const card = h("article", { class: `card message ${item.status === "new" ? "unread" : ""}`, dataset: { id: item.id } });
  const move = async (status, done) => {
    try {
      const updated = await api.patch(`/feedback/${item.id}`, { status });
      // Still in this folder (read ↔ unread): update in place; otherwise it leaves the list.
      const stays = (folder === "inbox" && ["new", "read"].includes(status)) || folder === status;
      if (stays) card.replaceWith(message(updated, folder, rerender));
      else leave(card, rerender);
      if (done) toast(done);
      refreshCounts(rerender);
    } catch (error) {
      showError(error);
    }
  };
  const remove = async () => {
    if (!(await confirm({ title: "Delete this message?", message: "It's deleted for good.", confirmLabel: "Delete", danger: true }))) return;
    try {
      await api.del(`/feedback/${item.id}`);
      leave(card, rerender);
      toast("Deleted");
      refreshCounts(rerender);
    } catch (error) {
      showError(error);
    }
  };
  const actions = {
    inbox: [
      item.status === "new"
        ? h("button", { class: "btn small ghost", on: { click: () => move("read") } }, icon("check"), "Mark read")
        : h("button", { class: "btn small ghost", text: "Mark unread", on: { click: () => move("new") } }),
      h("button", { class: "btn small ghost", on: { click: () => move("archived", "Archived") } }, icon("archive"), "Archive"),
      h("button", { class: "btn small ghost", on: { click: () => move("spam", "Moved to spam") } }, icon("spam"), "Spam"),
    ],
    archived: [h("button", { class: "btn small ghost", on: { click: () => move("read", "Moved to inbox") } }, icon("inbox"), "Move to inbox")],
    spam: [h("button", { class: "btn small ghost", on: { click: () => move("read", "Moved to inbox") } }, icon("inbox"), "Not spam")],
  }[folder];
  return fill(card,
    h("div", { class: "message-head" },
      item.status === "new" && h("span", { class: "dot", title: "Unread", style: { background: "var(--accent)" } }),
      h("span", { class: `chip ${kindTone}`, text: kindLabel }),
      item.repeats > 0 && h("span", { class: "chip", title: "The same text was sent again", text: `Sent ${item.repeats + 1}×` }),
      h("span", { class: "grow" }),
      h("time", { class: "hint", dateTime: new Date(item.createdAt * 1000).toISOString(), title: fullDate(item.createdAt), text: ago(item.createdAt) })),
    // dir=auto: Persian reads right to left, English left to right. Text only, never markup.
    h("div", { class: "message-text", dir: "auto", text: item.text }),
    h("div", { class: "message-foot" },
      h("span", { class: "hint", text: build(item) }),
      h("span", { class: "grow" }),
      actions,
      h("button", { class: "btn small ghost icon danger", "aria-label": "Delete", title: "Delete", on: { click: remove } }, icon("trash"))));
}

/** Takes a message off the list; the last one leaves the folder's empty state behind. */
function leave(card, rerender) {
  const list = card.parentElement;
  card.remove();
  if (list && !list.querySelector(".message")) rerender();
}

async function refreshCounts(rerender) {
  try {
    const counts = await api.get("/feedback/counts");
    publishCounts(counts);
    // The folder tabs show the counts too.
    const tabs = document.querySelector(".page-head .seg");
    if (tabs) tabs.replaceWith(head(counts, rerender).querySelector(".seg"));
  } catch {
    // The badge catches up on the next load.
  }
}

function publishCounts(counts) {
  document.dispatchEvent(new CustomEvent("feedback-counts", { detail: counts }));
}

function build(item) {
  const android = item.osVersion ? `Android ${ANDROID[item.osVersion] || `API ${item.osVersion}`}` : null;
  return [CHANNELS[item.channel] || item.channel, item.appVersion ? `version ${item.appVersion}` : "unknown version", android].filter(Boolean).join(" · ");
}

function ago(seconds) {
  const minutes = Math.max(0, Math.round((Date.now() / 1000 - seconds) / 60));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return days < 30 ? `${days} d ago` : fullDate(seconds);
}

function fullDate(seconds) {
  return new Date(seconds * 1000).toLocaleString("en-GB", { timeZone: "Asia/Tehran", dateStyle: "medium", timeStyle: "short" }) + " (Iran)";
}
