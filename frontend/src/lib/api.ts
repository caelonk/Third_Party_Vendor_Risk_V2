/** Thin typed fetch client. Cookies (httpOnly JWT) ride along automatically. */
const BASE = "/api/v1";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

// Endpoints that must not trigger a silent refresh-and-retry on 401.
const NO_REFRESH = ["/auth/login", "/auth/register", "/auth/refresh", "/auth/logout"];

let refreshing: Promise<boolean> | null = null;
function tryRefresh(): Promise<boolean> {
  if (!refreshing) {
    refreshing = fetch(BASE + "/auth/refresh", { method: "POST", credentials: "include" })
      .then((r) => r.ok)
      .catch(() => false)
      .finally(() => {
        refreshing = null;
      });
  }
  return refreshing;
}

async function request<T>(method: string, path: string, body?: unknown, retry = false): Promise<T> {
  const res = await fetch(BASE + path, {
    method,
    credentials: "include",
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  // Access token likely expired — refresh once (using the refresh cookie) and retry.
  if (res.status === 401 && !retry && !NO_REFRESH.some((p) => path.startsWith(p))) {
    if (await tryRefresh()) return request<T>(method, path, body, true);
  }

  if (res.status === 204) return undefined as T;

  let payload: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }

  if (!res.ok) {
    let detail = res.statusText;
    if (payload && typeof payload === "object" && "detail" in payload) {
      const d = (payload as { detail: unknown }).detail;
      if (Array.isArray(d)) {
        // FastAPI request-validation errors: [{ loc, msg, type }, ...]
        detail = d
          .map((e) =>
            e && typeof e === "object" && "msg" in e ? String((e as { msg: unknown }).msg) : String(e),
          )
          .join("; ");
      } else {
        detail = String(d);
      }
    } else if (typeof payload === "string" && payload) {
      detail = payload;
    }
    throw new ApiError(res.status, detail);
  }
  return payload as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body),
  del: <T>(path: string) => request<T>("DELETE", path),
};
