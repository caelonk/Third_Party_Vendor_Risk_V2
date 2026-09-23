import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useOrg } from "@/org/OrgProvider";
import type { CpeCandidate } from "@/lib/types";

/** Search the NVD CPE dictionary for a product name (>= 2 chars). */
export function useCpeSearch(query: string) {
  const { currentOrg } = useOrg();
  const orgId = currentOrg?.id;
  const q = query.trim();
  return useQuery({
    queryKey: ["cpe-search", orgId, q],
    queryFn: () =>
      api.get<CpeCandidate[]>(`/orgs/${orgId}/cpe-search?q=${encodeURIComponent(q)}`),
    enabled: !!orgId && q.length >= 2,
    staleTime: 5 * 60 * 1000, // CPE data is stable; cache within the session
  });
}
