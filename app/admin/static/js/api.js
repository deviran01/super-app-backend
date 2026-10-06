// Admin API client. Every request carries X-Superapp-Admin, which the server requires for
// anything that changes state (a cross-site page can't send it).

export class ApiError extends Error {
  constructor(status, detail) {
    const message = typeof detail === "string" ? detail : detail?.message || "Something went wrong";
    super(message);
    this.status = status;
    this.problems = (detail && detail.problems) || [];
  }
}

let onSignedOut = () => {};
export function whenSignedOut(fn) { onSignedOut = fn; }

async function request(method, path, body, contentType = "application/json") {
  const headers = { "X-Superapp-Admin": "1" };
  let payload = body;
  if (body !== undefined && contentType === "application/json") {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  } else if (body !== undefined) {
    headers["Content-Type"] = contentType;
  }
  let response;
  try {
    response = await fetch(`/admin/api${path}`, { method, headers, body: payload, credentials: "same-origin" });
  } catch {
    throw new ApiError(0, "Can't reach the server. Check your connection.");
  }
  const data = response.status === 204 ? null : await response.json().catch(() => null);
  if (response.status === 401 && path !== "/session") onSignedOut();
  if (!response.ok) {
    const detail = data?.detail;
    // FastAPI's own validation errors arrive as a list.
    if (Array.isArray(detail)) throw new ApiError(response.status, { message: "Invalid request", problems: detail.map((d) => ({ path: d.loc.join("."), message: d.msg })) });
    throw new ApiError(response.status, detail);
  }
  return data;
}

export const api = {
  get: (path) => request("GET", path),
  post: (path, body) => request("POST", path, body ?? {}),
  put: (path, body) => request("PUT", path, body),
  patch: (path, body) => request("PATCH", path, body),
  del: (path) => request("DELETE", path),
  upload: (path, file) => request("POST", path, file, file.type || "application/octet-stream"),
};
