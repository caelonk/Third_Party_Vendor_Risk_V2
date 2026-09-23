/**
 * Vendor list search / filter / sort — pure functions over the fetched list.
 *
 * State lives in the URL (see parseFilters / filtersToParams) so a filtered view
 * is shareable and survives refresh and back/forward.
 *
 * Honest-data rule: missing data sorts LAST in both directions. An unscored Max
 * CVSS is not 0.0, a never-synced vendor is not "oldest", and an unassessed
 * vendor's CVE/KEV counts are unknown — not zero, and not "lowest risk".
 */
import type { Tier, Vendor } from "@/lib/types";

export const TIERS: Tier[] = ["Critical", "High", "Medium", "Low", "Not Assessed"];

export type SortKey = "name" | "tier" | "max_cvss" | "cves" | "kev" | "last_sync";
export type SortDir = "asc" | "desc";
export type Mapping = "all" | "mapped" | "unmapped";

export interface VendorFilters {
  q: string;
  tiers: Tier[]; // empty = every tier
  kevOnly: boolean;
  mapping: Mapping;
  sort: SortKey;
  dir: SortDir;
}

export const DEFAULT_FILTERS: VendorFilters = {
  q: "",
  tiers: [],
  kevOnly: false,
  mapping: "all",
  sort: "tier",
  dir: "desc",
};

const SORT_KEYS: SortKey[] = ["name", "tier", "max_cvss", "cves", "kev", "last_sync"];

// The direction a column starts in when first clicked: names A-Z, everything
// else "most first" (riskiest, highest score, most CVEs, most recent sync).
const DEFAULT_DIR: Record<SortKey, SortDir> = {
  name: "asc",
  tier: "desc",
  max_cvss: "desc",
  cves: "desc",
  kev: "desc",
  last_sync: "desc",
};

// "Not Assessed" deliberately has no rank: it is unknown, not low.
const TIER_RANK: Partial<Record<Tier, number>> = { Critical: 4, High: 3, Medium: 2, Low: 1 };

// --------------------------------------------------------------------------- //
// URL state                                                                   //
// --------------------------------------------------------------------------- //
export function parseFilters(params: URLSearchParams): VendorFilters {
  const rawSort = params.get("sort");
  const sort = SORT_KEYS.includes(rawSort as SortKey) ? (rawSort as SortKey) : DEFAULT_FILTERS.sort;
  const dir = params.get("dir");
  const mapping = params.get("mapped");
  const requested = (params.get("tier") ?? "").split(",");
  return {
    q: params.get("q") ?? "",
    tiers: TIERS.filter((t) => requested.includes(t)),
    kevOnly: params.get("kev") === "1",
    mapping: mapping === "mapped" || mapping === "unmapped" ? mapping : "all",
    sort,
    dir: dir === "asc" || dir === "desc" ? dir : DEFAULT_DIR[sort],
  };
}

/** Serialize only non-default values, so an unfiltered view has a clean URL. */
export function filtersToParams(f: VendorFilters): URLSearchParams {
  const p = new URLSearchParams();
  if (f.q) p.set("q", f.q); // raw, so a trailing space survives while typing
  const tiers = TIERS.filter((t) => f.tiers.includes(t));
  if (tiers.length) p.set("tier", tiers.join(","));
  if (f.kevOnly) p.set("kev", "1");
  if (f.mapping !== "all") p.set("mapped", f.mapping);
  if (f.sort !== DEFAULT_FILTERS.sort || f.dir !== DEFAULT_FILTERS.dir) {
    p.set("sort", f.sort);
    p.set("dir", f.dir);
  }
  return p;
}

/** True when any filter narrows the list (sort order alone does not count). */
export function isFiltered(f: VendorFilters): boolean {
  return f.q.trim() !== "" || f.tiers.length > 0 || f.kevOnly || f.mapping !== "all";
}

// --------------------------------------------------------------------------- //
// Filter + sort                                                               //
// --------------------------------------------------------------------------- //
export function applyFilters(vendors: Vendor[], f: VendorFilters): Vendor[] {
  const q = f.q.trim().toLowerCase();
  return vendors.filter((v) => {
    if (q && !v.name.toLowerCase().includes(q) && !(v.cpe_prefix ?? "").toLowerCase().includes(q)) {
      return false;
    }
    if (f.tiers.length && !f.tiers.includes(v.assessment.tier)) return false;
    if (f.kevOnly && v.assessment.kev_count <= 0) return false;
    if (f.mapping === "mapped" && !v.is_mapped) return false;
    if (f.mapping === "unmapped" && v.is_mapped) return false;
    return true;
  });
}

function sortValue(v: Vendor, key: SortKey): number | string | null {
  const a = v.assessment;
  const assessed = a.tier !== "Not Assessed";
  switch (key) {
    case "name":
      return v.name.toLowerCase();
    case "tier":
      return TIER_RANK[a.tier] ?? null;
    case "max_cvss":
      return a.max_cvss; // null = unscored, never 0.0
    case "cves":
      return assessed ? a.cve_count : null;
    case "kev":
      return assessed ? a.kev_count : null;
    case "last_sync":
      return v.last_synced_at ? Date.parse(v.last_synced_at) : null;
  }
}

export function sortVendors(vendors: Vendor[], key: SortKey, dir: SortDir): Vendor[] {
  const sign = dir === "asc" ? 1 : -1;
  return [...vendors].sort((x, y) => {
    const a = sortValue(x, key);
    const b = sortValue(y, key);
    if (a === null || b === null) {
      // Missing data trails in both directions.
      if (a !== b) return a === null ? 1 : -1;
    } else if (a !== b) {
      const c =
        typeof a === "string" && typeof b === "string" ? a.localeCompare(b) : Number(a) - Number(b);
      if (c !== 0) return c * sign;
    }
    return x.name.localeCompare(y.name); // deterministic tie-break
  });
}

/** Clicking a header: toggle the active column, or start a new one naturally. */
export function nextSort(f: VendorFilters, key: SortKey): Pick<VendorFilters, "sort" | "dir"> {
  if (f.sort === key) return { sort: key, dir: f.dir === "asc" ? "desc" : "asc" };
  return { sort: key, dir: DEFAULT_DIR[key] };
}
