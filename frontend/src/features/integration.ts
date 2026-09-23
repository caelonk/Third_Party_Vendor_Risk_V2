import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useOrg } from "@/org/OrgProvider";
import type { Integration, IntegrationUpdate } from "@/lib/types";

export function useIntegration() {
  const { currentOrg } = useOrg();
  const orgId = currentOrg?.id;
  return useQuery({
    queryKey: ["integration", orgId],
    queryFn: () => api.get<Integration>(`/orgs/${orgId}/integration`),
    enabled: !!orgId,
  });
}

export function useUpdateIntegration() {
  const { currentOrg } = useOrg();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: IntegrationUpdate) =>
      api.put<Integration>(`/orgs/${currentOrg!.id}/integration`, input),
    onSuccess: (data) => qc.setQueryData(["integration", currentOrg?.id], data),
  });
}
