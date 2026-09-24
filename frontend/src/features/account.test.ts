import { describe, expect, it } from "vitest";
import type { SignInMethods } from "@/lib/types";
import { passwordMode, passwordProblems } from "./account";

const google = {
  provider: "google",
  email: "a@b.io",
  linked_at: "2026-09-24T10:00:00Z",
  last_login_at: null,
};
const methods = (has_password: boolean, linked: boolean): SignInMethods => ({
  has_password,
  identities: linked ? [google] : [],
});

describe("passwordMode", () => {
  it("greys out the form for a Google-created account until it's unlinked", () => {
    expect(passwordMode(methods(false, true))).toBe("locked");
    expect(passwordMode(methods(false, false))).toBe("create");
  });

  it("is a normal change-password form whenever a password exists", () => {
    expect(passwordMode(methods(true, true))).toBe("change");
    expect(passwordMode(methods(true, false))).toBe("change");
  });
});

describe("passwordProblems", () => {
  const ok = { current: "old-password", next: "new-password", confirm: "new-password" };

  it("accepts a valid change and a valid creation", () => {
    expect(passwordProblems("change", ok)).toBeNull();
    expect(passwordProblems("create", { ...ok, current: "" })).toBeNull();
  });

  it("explains what's wrong", () => {
    expect(passwordProblems("locked", ok)).toMatch(/Unlink Google/);
    expect(passwordProblems("change", { ...ok, current: "" })).toMatch(/current password/);
    expect(passwordProblems("create", { current: "", next: "short", confirm: "short" })).toMatch(
      /at least 8/,
    );
    expect(passwordProblems("create", { current: "", next: "new-password", confirm: "other-pass" })).toMatch(
      /don't match/,
    );
    expect(passwordProblems("change", { current: "same-pass-1", next: "same-pass-1", confirm: "same-pass-1" })).toMatch(
      /differs/,
    );
  });
});
