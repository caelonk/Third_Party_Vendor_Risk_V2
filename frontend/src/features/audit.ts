import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useOrg } from "@/org/OrgProvider";
import type { AuditEntry } from "@/lib/types";

/** Org activity log (admin+); pass `enabled` from the caller's role check. */
export function useAuditLog(enabled: boolean) {
  const { currentOrg } = useOrg();
  const orgId = currentOrg?.id;
  return useQuery({
    queryKey: ["audit-log", orgId],
    queryFn: () => api.get<AuditEntry[]>(`/orgs/${orgId}/audit-log?limit=100`),
    enabled: !!orgId && enabled,
  });
}
