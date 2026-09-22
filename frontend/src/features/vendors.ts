import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useOrg } from "@/org/OrgProvider";
import type { SyncRun, Vendor } from "@/lib/types";

export interface VendorInput {
  name: string;
  cpe_prefix?: string | null;
  annual_contract_value?: number | null;
  data_sensitivity?: string | null;
  business_criticality?: string | null;
  contract_renewal_date?: string | null;
}

function base(orgId: number) {
  return `/orgs/${orgId}/vendors`;
}

export function useVendors() {
  const { currentOrg } = useOrg();
  const orgId = currentOrg?.id;
  return useQuery({
    queryKey: ["vendors", orgId],
    queryFn: () => api.get<Vendor[]>(base(orgId!)),
    enabled: !!orgId,
  });
}

export function useVendor(vendorId: number) {
  const { currentOrg } = useOrg();
  const orgId = currentOrg?.id;
  return useQuery({
    queryKey: ["vendor", orgId, vendorId],
    queryFn: () => api.get<Vendor>(`${base(orgId!)}/${vendorId}`),
    enabled: !!orgId,
  });
}

export function useCreateVendor() {
  const { currentOrg } = useOrg();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: VendorInput) => api.post<Vendor>(base(currentOrg!.id), input),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["vendors", currentOrg?.id] }),
  });
}

export function useUpdateVendor(vendorId: number) {
  const { currentOrg } = useOrg();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: Partial<VendorInput>) =>
      api.patch<Vendor>(`${base(currentOrg!.id)}/${vendorId}`, input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["vendors", currentOrg?.id] });
      qc.invalidateQueries({ queryKey: ["vendor", currentOrg?.id, vendorId] });
    },
  });
}

export function useDeleteVendor() {
  const { currentOrg } = useOrg();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vendorId: number) => api.del(`${base(currentOrg!.id)}/${vendorId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["vendors", currentOrg?.id] }),
  });
}

export function useSyncVendor() {
  const { currentOrg } = useOrg();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vendorId: number) =>
      api.post<SyncRun>(`${base(currentOrg!.id)}/${vendorId}/sync`),
    onSuccess: (_run, vendorId) => {
      qc.invalidateQueries({ queryKey: ["vendors", currentOrg?.id] });
      qc.invalidateQueries({ queryKey: ["vendor", currentOrg?.id, vendorId] });
      qc.invalidateQueries({ queryKey: ["dashboard", currentOrg?.id] });
    },
  });
}
