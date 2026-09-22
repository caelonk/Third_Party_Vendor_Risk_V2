import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useOrg } from "@/org/OrgProvider";
import type { DashboardSummary, HeatmapCell, TopRiskItem, WatchlistItem } from "@/lib/types";

function dash(orgId: number) {
  return `/orgs/${orgId}/dashboard`;
}

export function useSummary() {
  const { currentOrg } = useOrg();
  const orgId = currentOrg?.id;
  return useQuery({
    queryKey: ["dashboard", orgId, "summary"],
    queryFn: () => api.get<DashboardSummary>(`${dash(orgId!)}/summary`),
    enabled: !!orgId,
  });
}

export function useHeatmap() {
  const { currentOrg } = useOrg();
  const orgId = currentOrg?.id;
  return useQuery({
    queryKey: ["dashboard", orgId, "heatmap"],
    queryFn: () => api.get<{ cells: HeatmapCell[] }>(`${dash(orgId!)}/heatmap`),
    enabled: !!orgId,
  });
}

export function useWatchlist() {
  const { currentOrg } = useOrg();
  const orgId = currentOrg?.id;
  return useQuery({
    queryKey: ["dashboard", orgId, "watchlist"],
    queryFn: () => api.get<WatchlistItem[]>(`${dash(orgId!)}/watchlist`),
    enabled: !!orgId,
  });
}

export function useTopRisk() {
  const { currentOrg } = useOrg();
  const orgId = currentOrg?.id;
  return useQuery({
    queryKey: ["dashboard", orgId, "top-risk"],
    queryFn: () => api.get<TopRiskItem[]>(`${dash(orgId!)}/top-risk`),
    enabled: !!orgId,
  });
}
