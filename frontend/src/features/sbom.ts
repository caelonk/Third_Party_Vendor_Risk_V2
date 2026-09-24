import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useOrg } from "@/org/OrgProvider";
import type { SbomCandidate, SbomImportResult, SbomPreview } from "@/lib/types";

export const MAX_SBOM_BYTES = 10 * 1024 * 1024; // mirrors the API guard

// --------------------------------------------------------------------------- //
// Pure helpers (unit-tested). Rows are keyed by index: an in-file "duplicate"  //
// row can share its name with the row it duplicates.                          //
// --------------------------------------------------------------------------- //
export const isImportable = (c: SbomCandidate) => c.status === "new";

/** Pre-select new, CPE-mapped rows. Unmapped rows are opt-in so a large SBOM's
 *  transitive libraries don't flood the vendor list as "Not Assessed". */
export function defaultSelection(candidates: SbomCandidate[]): Set<number> {
  const s = new Set<number>();
  candidates.forEach((c, i) => {
    if (isImportable(c) && c.cpe_prefix) s.add(i);
  });
  return s;
}

export function selectAll(candidates: SbomCandidate[], mappedOnly: boolean): Set<number> {
  const s = new Set<number>();
  candidates.forEach((c, i) => {
    if (isImportable(c) && (!mappedOnly || c.cpe_prefix)) s.add(i);
  });
  return s;
}

export function summarize(candidates: SbomCandidate[], selected: Set<number>) {
  let mapped = 0;
  let unmapped = 0;
  selected.forEach((i) => {
    const c = candidates[i];
    if (!c || !isImportable(c)) return;
    if (c.cpe_prefix) mapped += 1;
    else unmapped += 1;
  });
  return { total: mapped + unmapped, mapped, unmapped };
}

export function toImportItems(candidates: SbomCandidate[], selected: Set<number>) {
  return candidates
    .map((c, i) => ({ c, i }))
    .filter(({ c, i }) => selected.has(i) && isImportable(c))
    .map(({ c }) => ({ name: c.name, cpe_prefix: c.cpe_prefix }));
}

/** Read and parse an uploaded SBOM file, with friendly errors. */
export async function readSbomFile(file: File): Promise<object> {
  if (file.size > MAX_SBOM_BYTES) {
    throw new Error(`That file is larger than ${MAX_SBOM_BYTES / (1024 * 1024)} MB.`);
  }
  let doc: unknown;
  try {
    doc = JSON.parse(await file.text());
  } catch {
    throw new Error("That file isn't valid JSON. Export the SBOM as CycloneDX or SPDX JSON.");
  }
  if (!doc || typeof doc !== "object" || Array.isArray(doc)) {
    throw new Error("Expected a CycloneDX or SPDX JSON document.");
  }
  return doc as object;
}

// --------------------------------------------------------------------------- //
// API hooks                                                                   //
// --------------------------------------------------------------------------- //
export function useSbomPreview() {
  const { currentOrg } = useOrg();
  return useMutation({
    mutationFn: (doc: object) =>
      api.post<SbomPreview>(`/orgs/${currentOrg!.id}/sbom/preview`, doc),
  });
}

export function useSbomImport() {
  const { currentOrg } = useOrg();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (items: { name: string; cpe_prefix: string | null }[]) =>
      api.post<SbomImportResult>(`/orgs/${currentOrg!.id}/sbom/import`, { items }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["vendors", currentOrg?.id] });
      qc.invalidateQueries({ queryKey: ["dashboard", currentOrg?.id] });
      qc.invalidateQueries({ queryKey: ["audit-log", currentOrg?.id] });
    },
  });
}
