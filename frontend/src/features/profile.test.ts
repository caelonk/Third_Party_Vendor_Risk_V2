import { describe, expect, it } from "vitest";
import {
  MAX_SOURCE_BYTES,
  avatarFileProblem,
  describeBrowser,
  signInMethodLabel,
} from "./profile";

describe("describeBrowser", () => {
  const cases: [string, string][] = [
    [
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
      "Chrome on Windows",
    ],
    [
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0",
      "Edge on Windows",
    ],
    [
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
      "Safari on macOS",
    ],
    [
      "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
      "Safari on iPhone",
    ],
    [
      "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Mobile Safari/537.36",
      "Chrome on Android",
    ],
    ["Mozilla/5.0 (X11; Linux x86_64; rv:143.0) Gecko/20100101 Firefox/143.0", "Firefox on Linux"],
  ];

  it.each(cases)("%s", (ua, expected) => {
    expect(describeBrowser(ua)).toBe(expected);
  });

  it("names only what it recognises", () => {
    expect(describeBrowser("curl/8.9.1")).toBe("Unknown device");
    expect(describeBrowser("SomeApp/1.0 (Windows NT 10.0)")).toBe("Windows");
    expect(describeBrowser(null)).toBe("Unknown device");
    expect(describeBrowser("")).toBe("Unknown device");
  });
});

describe("signInMethodLabel", () => {
  it("names the known methods and tidies an unknown one", () => {
    expect(signInMethodLabel("password")).toBe("Password");
    expect(signInMethodLabel("google")).toBe("Google");
    expect(signInMethodLabel("okta")).toBe("Okta");
  });
});

describe("avatarFileProblem", () => {
  it("accepts PNG, JPEG and WebP", () => {
    for (const type of ["image/png", "image/jpeg", "image/webp"]) {
      expect(avatarFileProblem({ type, size: 1_000_000 })).toBeNull();
    }
  });

  it("refuses other file types", () => {
    expect(avatarFileProblem({ type: "image/gif", size: 10 })).toMatch(/PNG, JPEG or WebP/);
    expect(avatarFileProblem({ type: "application/pdf", size: 10 })).toMatch(/PNG, JPEG or WebP/);
    expect(avatarFileProblem({ type: "", size: 10 })).toMatch(/PNG, JPEG or WebP/);
  });

  it("refuses an original too large to resize in the browser", () => {
    expect(avatarFileProblem({ type: "image/jpeg", size: MAX_SOURCE_BYTES })).toBeNull();
    expect(avatarFileProblem({ type: "image/jpeg", size: MAX_SOURCE_BYTES + 1 })).toMatch(/25 MB/);
  });
});
