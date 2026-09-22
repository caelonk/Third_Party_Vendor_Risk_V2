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

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method,
    credentials: "include",
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

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
