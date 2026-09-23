import { describe, expect, it } from "vitest";
import type { Tier, Vendor } from "@/lib/types";
import {
  DEFAULT_FILTERS,
  applyFilters,
  filtersToParams,
  isFiltered,
  nextSort,
  parseFilters,
  sortVendors,
  type VendorFilters,
} from "./vendorFilters";

interface Opts {
  tier?: Tier;
  max_cvss?: number | null;
  cve?: number;
  kev?: number;
  mapped?: boolean;
  prefix?: string | null;
  synced?: string | null;
}

function vendor(id: number, name: string, o: Opts = {}): Vendor {
  const tier = o.tier ?? "Not Assessed";
  return {
    id,
    name,
    cpe_prefix: o.prefix ?? null,
    match_method: null,
    is_mapped: o.mapped ?? tier !== "Not Assessed",
    annual_contract_value: null,
    data_sensitivity: null,
    business_criticality: null,
    contract_renewal_date: null,
    last_synced_at: o.synced ?? null,
    assessment: {
      tier,
      threat_band: null,
      exposure_band: null,
      max_cvss: o.max_cvss ?? null,
      cve_count: o.cve ?? 0,
      kev_count: o.kev ?? 0,
    },
  };
}

const fortinet = vendor(1, "Fortinet FortiOS", {
  tier: "High", max_cvss: 9.8, cve: 30, kev: 20,
  prefix: "cpe:2.3:o:fortinet:fortios", synced: "2026-09-23T20:01:00Z",
});
const openssh = vendor(2, "OpenSSH", {
  tier: "Low", max_cvss: 7.7, cve: 14,
  prefix: "cpe:2.3:a:openbsd:openssh", synced: "2026-09-23T05:50:00Z",
});
const acme = vendor(3, "Acme Unmapped"); // Not Assessed: no data at all
const zeta = vendor(4, "Zeta Unscored", {
  tier: "Medium", max_cvss: null, cve: 2,
  prefix: "cpe:2.3:a:zeta:zeta", synced: "2026-09-20T00:00:00Z",
});
const ALL = [fortinet, openssh, acme, zeta];

const names = (vs: Vendor[]) => vs.map((v) => v.name);
const withF = (patch: Partial<VendorFilters>): VendorFilters => ({ ...DEFAULT_FILTERS, ...patch });

describe("applyFilters", () => {
  it("searches name and CPE prefix, case-insensitively", () => {
    expect(names(applyFilters(ALL, withF({ q: "FORTI" })))).toEqual(["Fortinet FortiOS"]);
    expect(names(applyFilters(ALL, withF({ q: "openbsd" })))).toEqual(["OpenSSH"]);
    expect(applyFilters(ALL, withF({ q: "   " }))).toHaveLength(4); // blank = no filter
  });

  it("filters by tier set, including Not Assessed", () => {
    expect(names(applyFilters(ALL, withF({ tiers: ["High", "Low"] })))).toEqual([
      "Fortinet FortiOS",
      "OpenSSH",
    ]);
    expect(names(applyFilters(ALL, withF({ tiers: ["Not Assessed"] })))).toEqual(["Acme Unmapped"]);
  });

  it("filters to KEV-exposed vendors and by mapping status", () => {
    expect(names(applyFilters(ALL, withF({ kevOnly: true })))).toEqual(["Fortinet FortiOS"]);
    expect(names(applyFilters(ALL, withF({ mapping: "unmapped" })))).toEqual(["Acme Unmapped"]);
    expect(applyFilters(ALL, withF({ mapping: "mapped" }))).toHaveLength(3);
  });

  it("combines filters with AND", () => {
    expect(applyFilters(ALL, withF({ q: "open", kevOnly: true }))).toEqual([]);
  });
});

describe("sortVendors — honest-data ordering", () => {
  it("defaults to riskiest first, with Not Assessed last", () => {
    expect(names(sortVendors(ALL, "tier", "desc"))).toEqual([
      "Fortinet FortiOS", "Zeta Unscored", "OpenSSH", "Acme Unmapped",
    ]);
  });

  it("keeps Not Assessed last even ascending — it is not 'lowest risk'", () => {
    expect(names(sortVendors(ALL, "tier", "asc"))).toEqual([
      "OpenSSH", "Zeta Unscored", "Fortinet FortiOS", "Acme Unmapped",
    ]);
  });

  it("sorts unscored Max CVSS last in both directions, never as 0.0", () => {
    const asc = names(sortVendors(ALL, "max_cvss", "asc"));
    const desc = names(sortVendors(ALL, "max_cvss", "desc"));
    expect(asc.slice(0, 2)).toEqual(["OpenSSH", "Fortinet FortiOS"]);
    expect(desc.slice(0, 2)).toEqual(["Fortinet FortiOS", "OpenSSH"]);
    // Both unscored vendors trail, in name order.
    expect(asc.slice(2)).toEqual(["Acme Unmapped", "Zeta Unscored"]);
    expect(desc.slice(2)).toEqual(["Acme Unmapped", "Zeta Unscored"]);
  });

  it("treats an unassessed vendor's CVE count as unknown, not zero", () => {
    // Ascending CVEs must not surface the never-looked-up vendor as "fewest CVEs".
    expect(names(sortVendors(ALL, "cves", "asc"))).toEqual([
      "Zeta Unscored", "OpenSSH", "Fortinet FortiOS", "Acme Unmapped",
    ]);
  });

  it("sorts never-synced vendors last by last sync", () => {
    expect(names(sortVendors(ALL, "last_sync", "desc"))).toEqual([
      "Fortinet FortiOS", "OpenSSH", "Zeta Unscored", "Acme Unmapped",
    ]);
    expect(names(sortVendors(ALL, "last_sync", "asc"))).toEqual([
      "Zeta Unscored", "OpenSSH", "Fortinet FortiOS", "Acme Unmapped",
    ]);
  });

  it("sorts by name and does not mutate its input", () => {
    const input = [...ALL];
    expect(names(sortVendors(input, "name", "asc"))).toEqual([
      "Acme Unmapped", "Fortinet FortiOS", "OpenSSH", "Zeta Unscored",
    ]);
    expect(input).toEqual(ALL);
  });
});

describe("URL state", () => {
  it("round-trips filters through search params", () => {
    const f = withF({ q: "forti ", tiers: ["Low", "High"], kevOnly: true, mapping: "mapped", sort: "max_cvss", dir: "asc" });
    expect(parseFilters(filtersToParams(f))).toEqual({ ...f, tiers: ["High", "Low"] });
  });

  it("omits defaults so an unfiltered view has a clean URL", () => {
    expect(filtersToParams(DEFAULT_FILTERS).toString()).toBe("");
  });

  it("ignores junk params instead of breaking", () => {
    const f = parseFilters(new URLSearchParams("tier=Bogus,High&sort=nope&dir=up&mapped=maybe&kev=yes"));
    expect(f).toEqual(withF({ tiers: ["High"] }));
  });

  it("reports whether any filter is active (sort alone is not a filter)", () => {
    expect(isFiltered(DEFAULT_FILTERS)).toBe(false);
    expect(isFiltered(withF({ sort: "name", dir: "asc" }))).toBe(false);
    expect(isFiltered(withF({ kevOnly: true }))).toBe(true);
  });
});

describe("nextSort", () => {
  it("toggles direction on the active column", () => {
    expect(nextSort(withF({ sort: "tier", dir: "desc" }), "tier")).toEqual({ sort: "tier", dir: "asc" });
  });

  it("starts a new column in its natural direction", () => {
    expect(nextSort(DEFAULT_FILTERS, "name")).toEqual({ sort: "name", dir: "asc" });
    expect(nextSort(DEFAULT_FILTERS, "max_cvss")).toEqual({ sort: "max_cvss", dir: "desc" });
  });
});
