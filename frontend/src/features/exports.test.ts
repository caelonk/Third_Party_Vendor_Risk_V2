import { describe, expect, it } from "vitest";
import type { ExportJob, ExportStatus } from "@/lib/types";
import { downloadPath, fmtBytes, POLL_MS, pollInterval, settleWaiting } from "./exports";

const job = (id: number, status: ExportStatus): ExportJob => ({
  id,
  format: "csv",
  status,
  filename: status === "succeeded" ? `f${id}.csv` : null,
  size_bytes: null,
  error: null,
  requested_by: "a@b.io",
  created_at: "2026-09-24T10:00:00Z",
  completed_at: null,
  expires_at: null,
});

describe("pollInterval", () => {
  it("polls only while a job is queued or running", () => {
    expect(pollInterval(undefined)).toBe(false);
    expect(pollInterval([])).toBe(false);
    expect(pollInterval([job(1, "succeeded"), job(2, "failed"), job(3, "expired")])).toBe(false);
    expect(pollInterval([job(1, "succeeded"), job(2, "queued")])).toBe(POLL_MS);
    expect(pollInterval([job(1, "running")])).toBe(POLL_MS);
  });
});

describe("settleWaiting", () => {
  it("downloads only this tab's jobs, once they succeed", () => {
    const jobs = [job(1, "succeeded"), job(2, "running"), job(3, "failed"), job(4, "succeeded")];
    // 4 finished too, but this tab never asked for it: no surprise download.
    expect(settleWaiting(jobs, [1, 2, 3])).toEqual({ ready: [1], settled: [1, 3] });
  });

  it("keeps waiting while nothing has finished", () => {
    expect(settleWaiting([job(1, "queued")], [1])).toEqual({ ready: [], settled: [] });
  });

  it("stops waiting on an expired job without downloading it", () => {
    expect(settleWaiting([job(5, "expired")], [5])).toEqual({ ready: [], settled: [5] });
  });
});

describe("formatting", () => {
  it("formats sizes honestly (unknown is a dash, not 0)", () => {
    expect(fmtBytes(null)).toBe("—");
    expect(fmtBytes(0)).toBe("0 B");
    expect(fmtBytes(512)).toBe("512 B");
    expect(fmtBytes(1536)).toBe("1.5 KB");
    expect(fmtBytes(48 * 1024)).toBe("48 KB");
    expect(fmtBytes(3 * 1024 * 1024)).toBe("3.0 MB");
  });

  it("builds the same-origin download path", () => {
    expect(downloadPath(7, 42)).toBe("/api/v1/orgs/7/exports/42/download");
  });
});
