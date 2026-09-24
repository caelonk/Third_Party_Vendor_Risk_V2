import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "./api";

function respond(status: number, body: string, headers: Record<string, string> = {}) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(body, { status, headers })));
}

async function failure(): Promise<ApiError> {
  try {
    await api.get("/anything");
  } catch (e) {
    return e as ApiError;
  }
  throw new Error("expected the request to fail");
}

afterEach(() => vi.unstubAllGlobals());

describe("api error messages", () => {
  it("turns a generic 500 into a friendly message with the reference", async () => {
    respond(500, JSON.stringify({ detail: "Internal server error", request_id: "req-abc12345" }), {
      "X-Request-ID": "req-abc12345",
    });
    const err = await failure();
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(500);
    expect(err.requestId).toBe("req-abc12345");
    expect(err.message).toBe("Something went wrong on our side. Reference: req-abc12345");
  });

  it("keeps a deliberate 5xx message and appends the reference", async () => {
    respond(503, JSON.stringify({ detail: "PDF rendering is not available on this server." }), {
      "X-Request-ID": "req-def67890",
    });
    expect((await failure()).message).toBe(
      "PDF rendering is not available on this server. Reference: req-def67890",
    );
  });

  it("replaces a proxy's HTML error page with the generic message", async () => {
    respond(502, "<html><body>Bad Gateway</body></html>", { "content-type": "text/html" });
    expect((await failure()).message).toBe("Something went wrong on our side. Please try again.");
  });

  it("leaves 4xx details untouched", async () => {
    respond(404, JSON.stringify({ detail: "Vendor not found" }), { "X-Request-ID": "req-x1234567" });
    const err = await failure();
    expect(err.message).toBe("Vendor not found");
    expect(err.requestId).toBe("req-x1234567");
  });
});
