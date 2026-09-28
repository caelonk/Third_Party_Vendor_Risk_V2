import { useMutation, useQuery } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { useOrg } from "@/org/OrgProvider";
import type { BillingSummary, Plan, Usage } from "@/lib/types";

// --------------------------------------------------------------------------- //
// Pure helpers (unit-tested)                                                  //
// --------------------------------------------------------------------------- //

/** A 402 from the API: the org's plan doesn't allow it; upgrading would. */
export const isPlanLimit = (e: unknown) => e instanceof ApiError && e.status === 402;

export type MeterState = "unlimited" | "ok" | "full" | "over";

/** Fill fraction + state for a usage meter. Near-full is said in text ("2 left"),
 *  not with a third color: only "at/over the limit" changes the fill. */
export function meter(u: Usage): { state: MeterState; fraction: number; caption: string } {
  if (u.limit === null) return { state: "unlimited", fraction: 0, caption: `${u.used.toLocaleString()} · unlimited` };
  const fraction = u.limit > 0 ? Math.min(u.used / u.limit, 1) : 1;
  if (u.used > u.limit) {
    return { state: "over", fraction, caption: `${u.used.toLocaleString()} of ${u.limit.toLocaleString()} · over the limit` };
  }
  if (u.used === u.limit) {
    return { state: "full", fraction, caption: `${u.used.toLocaleString()} of ${u.limit.toLocaleString()} · limit reached` };
  }
  const left = u.limit - u.used;
  return { state: "ok", fraction, caption: `${u.used.toLocaleString()} of ${u.limit.toLocaleString()} · ${left.toLocaleString()} left` };
}

export function planFeatures(p: Plan): string[] {
  return [
    p.max_vendors === null ? "Unlimited vendors" : `Up to ${p.max_vendors.toLocaleString()} vendors`,
    p.max_members === null ? "Unlimited members" : `Up to ${p.max_members} members`,
    p.min_sync_hours === 1 ? "Hourly auto-sync" : `Auto-sync every ${p.min_sync_hours}h`,
    p.pdf_reports ? "CSV + PDF reports" : "CSV exports",
  ];
}

export function priceLabel(p: Plan): string {
  return p.price_usd_month === 0 ? "$0" : `$${p.price_usd_month}/mo`;
}

const STATUS_LABELS: Record<string, string> = {
  active: "Active",
  trialing: "Trial",
  past_due: "Payment past due",
  canceled: "Canceled",
  unpaid: "Unpaid",
  incomplete: "Payment incomplete",
  incomplete_expired: "Expired",
  paused: "Paused",
};

export function statusLabel(b: Pick<BillingSummary, "status" | "has_subscription" | "plan">): string {
  if (b.status && b.has_subscription) return STATUS_LABELS[b.status] ?? b.status;
  return b.plan.id === "free" ? "No subscription" : "Assigned plan";
}

// --------------------------------------------------------------------------- //
// API hooks                                                                   //
// --------------------------------------------------------------------------- //
export function useBilling(opts: { pollMs?: number | false; enabled?: boolean } = {}) {
  const { currentOrg } = useOrg();
  const orgId = currentOrg?.id;
  return useQuery({
    queryKey: ["billing", orgId],
    queryFn: () => api.get<BillingSummary>(`/orgs/${orgId}/billing`),
    enabled: !!orgId && (opts.enabled ?? true),
    refetchInterval: opts.pollMs ?? false,
    staleTime: 0, // usage counts must be current when the card mounts
  });
}

/** Both return a URL on the provider's hosted pages: go there (full page). */
export function useStartCheckout() {
  const { currentOrg } = useOrg();
  return useMutation({
    mutationFn: (plan: "team" | "business") =>
      api.post<{ url: string }>(`/orgs/${currentOrg!.id}/billing/checkout`, { plan }),
    onSuccess: ({ url }) => window.location.assign(url),
  });
}

export function useOpenPortal() {
  const { currentOrg } = useOrg();
  return useMutation({
    mutationFn: () => api.post<{ url: string }>(`/orgs/${currentOrg!.id}/billing/portal`),
    onSuccess: ({ url }) => window.location.assign(url),
  });
}
