import { describe, expect, it } from "vitest";
import { googleStartUrl, SSO_ERRORS, ssoErrorMessage } from "./sso";

describe("ssoErrorMessage", () => {
  it("maps known codes and falls back to a generic message", () => {
    expect(ssoErrorMessage(null)).toBeNull();
    expect(ssoErrorMessage("")).toBeNull();
    expect(ssoErrorMessage("cancelled")).toBe(SSO_ERRORS.cancelled);
    expect(ssoErrorMessage("unverified")).toMatch(/isn't verified/);
    // Unknown (or tampered) codes never echo back into the page.
    expect(ssoErrorMessage("<b>nope</b>")).toBe(SSO_ERRORS.failed);
  });
});

describe("googleStartUrl", () => {
  it("passes a same-site return path", () => {
    expect(googleStartUrl()).toBe("/api/v1/auth/google/start?next=%2F");
    expect(googleStartUrl("/vendors?tier=High")).toBe(
      "/api/v1/auth/google/start?next=%2Fvendors%3Ftier%3DHigh",
    );
  });

  it("drops anything that could leave the site", () => {
    expect(googleStartUrl("//evil.example")).toBe("/api/v1/auth/google/start?next=%2F");
    expect(googleStartUrl("https://evil.example")).toBe("/api/v1/auth/google/start?next=%2F");
  });
});
