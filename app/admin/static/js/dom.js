// Tiny DOM helpers. Text always goes through textContent, never innerHTML: names and
// URLs come from the catalog and must never be interpreted as markup.

export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value == null || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "text") el.textContent = value;
    else if (key === "on") for (const [event, fn] of Object.entries(value)) el.addEventListener(event, fn);
    else if (key === "style") Object.assign(el.style, value);
    else if (key === "dataset") Object.assign(el.dataset, value);
    else if (key in el && typeof value !== "string") el[key] = value;
    else el.setAttribute(key, value === true ? "" : value);
  }
  append(el, children);
  return el;
}

export function append(parent, children) {
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false) continue;
    parent.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return parent;
}

/** Replaces the children of `el`; arrays are flattened, null/false skipped. */
export function fill(el, ...children) {
  clear(el);
  return append(el, children);
}

export function clear(el) {
  while (el.firstChild) el.firstChild.remove();
  return el;
}

const ICONS = {
  overview: "M4 13h6V4H4v9Zm0 7h6v-5H4v5Zm10 0h6v-9h-6v9Zm0-16v5h6V4h-6Z",
  apps: "M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z",
  categories: "M3 7.5 12 3l9 4.5-9 4.5-9-4.5Zm0 4.5 9 4.5 9-4.5M3 16.5 12 21l9-4.5",
  compare: "M7 7h13m0 0-3.5-3.5M20 7l-3.5 3.5M17 17H4m0 0 3.5-3.5M4 17l3.5 3.5",
  releases: "M12 3v12m0 0-4-4m4 4 4-4M5 21h14",
  settings: "M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Zm7.4-2.5.9 1.6-2 3.4-1.8-.4a7 7 0 0 1-2 1.2L14 20.5h-4l-.5-1.7a7 7 0 0 1-2-1.2l-1.8.4-2-3.4.9-1.6a7 7 0 0 1 0-2.3l-.9-1.6 2-3.4 1.8.4a7 7 0 0 1 2-1.2L10 3.5h4l.5 1.7a7 7 0 0 1 2 1.2l1.8-.4 2 3.4-.9 1.6a7 7 0 0 1 0 2.3Z",
  history: "M3 12a9 9 0 1 0 3-6.7M3 4v4h4m5-1v5l3 2",
  users: "M16 19v-1a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v1m7-9a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm8-4a3 3 0 0 1 0 6m5 9v-1a4 4 0 0 0-3-3.9",
  logout: "M15 12H4m0 0 4-4m-4 4 4 4M13 4h5a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-5",
  plus: "M12 5v14M5 12h14",
  search: "m20 20-4.5-4.5M10.5 17a6.5 6.5 0 1 1 0-13 6.5 6.5 0 0 1 0 13Z",
  edit: "M4 20h4L19 9l-4-4L4 16v4Zm9-13 4 4",
  trash: "M5 7h14m-9 4v6m4-6v6M6 7l1 13h10l1-13M9 7V4h6v3",
  grip: "M9 6h.01M15 6h.01M9 12h.01M15 12h.01M9 18h.01M15 18h.01",
  upload: "M12 16V4m0 0-4 4m4-4 4 4M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3",
  store: "M4 9h16l-1 11H5L4 9Zm4 0V7a4 4 0 1 1 8 0v2",
  close: "M6 6l12 12M18 6 6 18",
  menu: "M4 7h16M4 12h16M4 17h16",
  star: "m12 4 2.4 5 5.6.6-4.2 3.8 1.2 5.6-5-2.9-5 2.9 1.2-5.6L4 9.6 9.6 9 12 4Z",
  wrench: "M14.5 6.5a4 4 0 0 0 5 5L13 18a2.1 2.1 0 0 1-3-3l6.5-6.5Zm0 0L11 3a4 4 0 0 0-5 5l3.5 3.5",
  external: "M14 4h6v6m0-6-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5",
  check: "m5 12.5 4.5 4.5L19 7.5",
  key: "M15 9a3 3 0 1 1-6 0 3 3 0 0 1 6 0Zm-3 3v9m0-4h3m-3 3h2",
  chart: "M4 20V10m6 10V4m6 16v-7m4 7H3",
  refresh: "M20 12a8 8 0 1 1-2.3-5.7M20 4v5h-5",
  message: "M5 5h14a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1h-8l-4 3v-3H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1Zm3 5h8m-8 3h5",
  inbox: "M4 13h4l1.5 2.5h5L16 13h4M5.5 5h13L20 13v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-5l1.5-8Z",
  archive: "M4 5h16v4H4zM5 9v9a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V9M10 13h4",
  spam: "M12 3 4.5 6v5.5c0 4.4 3.1 8.2 7.5 9.5 4.4-1.3 7.5-5.1 7.5-9.5V6L12 3Zm0 5.5v4m0 3h.01",
};

export function icon(name) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", "18");
  svg.setAttribute("height", "18");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", name === "grip" ? "3" : "1.7");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS(ns, "path");
  path.setAttribute("d", ICONS[name] || "");
  svg.append(path);
  return svg;
}
