import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useOrg } from "@/org/OrgProvider";
import type { PortfolioTrendPoint, VendorTrendPoint } from "@/lib/types";

export function useVendorTrend(vendorId: number) {
  const { currentOrg } = useOrg();
  const orgId = currentOrg?.id;
  return useQuery({
    queryKey: ["vendor-trend", orgId, vendorId],
    queryFn: () => api.get<VendorTrendPoint[]>(`/orgs/${orgId}/vendors/${vendorId}/trend`),
    enabled: !!orgId,
  });
}

export function usePortfolioTrend() {
  const { currentOrg } = useOrg();
  const orgId = currentOrg?.id;
  return useQuery({
    queryKey: ["dashboard", orgId, "snapshots"],
    queryFn: () => api.get<PortfolioTrendPoint[]>(`/orgs/${orgId}/snapshots`),
    enabled: !!orgId,
  });
}
