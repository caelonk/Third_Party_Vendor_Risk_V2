import { describe, expect, it } from "vitest";
import type { SbomCandidate } from "@/lib/types";
import {
  MAX_SBOM_BYTES,
  defaultSelection,
  readSbomFile,
  selectAll,
  summarize,
  toImportItems,
} from "./sbom";

function cand(name: string, cpe: string | null, status: SbomCandidate["status"] = "new"): SbomCandidate {
  return { name, cpe_prefix: cpe, versions: [], component_count: 1, supplier: null, status };
}

const CANDS: SbomCandidate[] = [
  cand("Apache Log4j", "cpe:2.3:a:apache:log4j"), // 0 new, mapped
  cand("Openssl", "cpe:2.3:a:openssl:openssl", "exists"), // 1 already added
  cand("Zlib", "cpe:2.3:a:zlib:zlib"), // 2 new, mapped
  cand("lodash", null), // 3 new, unmapped
  cand("Zlib", null, "duplicate"), // 4 duplicate in file
];

describe("selection", () => {
  it("pre-selects only new, CPE-mapped rows", () => {
    expect([...defaultSelection(CANDS)]).toEqual([0, 2]);
  });

  it("select-all can include unmapped rows but never exists/duplicate", () => {
    expect([...selectAll(CANDS, true)]).toEqual([0, 2]);
    expect([...selectAll(CANDS, false)]).toEqual([0, 2, 3]);
  });

  it("summarizes and builds import items only from importable selected rows", () => {
    const sel = new Set([0, 1, 3, 4]); // 1 and 4 are not importable
    expect(summarize(CANDS, sel)).toEqual({ total: 2, mapped: 1, unmapped: 1 });
    expect(toImportItems(CANDS, sel)).toEqual([
      { name: "Apache Log4j", cpe_prefix: "cpe:2.3:a:apache:log4j" },
      { name: "lodash", cpe_prefix: null },
    ]);
  });
});

describe("readSbomFile", () => {
  const file = (text: string) => new File([text], "bom.json", { type: "application/json" });

  it("parses a JSON object", async () => {
    await expect(readSbomFile(file('{"bomFormat":"CycloneDX"}'))).resolves.toEqual({
      bomFormat: "CycloneDX",
    });
  });

  it("rejects non-JSON and non-object JSON with friendly messages", async () => {
    await expect(readSbomFile(file("<bom/>"))).rejects.toThrow(/isn't valid JSON/);
    await expect(readSbomFile(file("[1,2]"))).rejects.toThrow(/CycloneDX or SPDX/);
  });

  it("rejects files over the size limit before reading them", async () => {
    const big = { size: MAX_SBOM_BYTES + 1, text: () => Promise.reject(new Error("read")) } as unknown as File;
    await expect(readSbomFile(big)).rejects.toThrow(/larger than 10 MB/);
  });
});
