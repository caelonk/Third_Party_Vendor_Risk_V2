import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useOrg } from "@/org/OrgProvider";
import type { AlertChannel, AlertRule, AlertType, Notification } from "@/lib/types";

function orgBase(orgId: number) {
  return `/orgs/${orgId}`;
}

export function useAlertRules() {
  const { currentOrg } = useOrg();
  const orgId = currentOrg?.id;
  return useQuery({
    queryKey: ["alert-rules", orgId],
    queryFn: () => api.get<AlertRule[]>(`${orgBase(orgId!)}/alert-rules`),
    enabled: !!orgId,
  });
}

export function useCreateRule() {
  const { currentOrg } = useOrg();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: { type: AlertType; channel: AlertChannel; config?: Record<string, unknown> }) =>
      api.post<AlertRule>(`${orgBase(currentOrg!.id)}/alert-rules`, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alert-rules", currentOrg?.id] }),
  });
}

export function useUpdateRule() {
  const { currentOrg } = useOrg();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...input }: { id: number; is_active?: boolean; config?: Record<string, unknown> }) =>
      api.patch<AlertRule>(`${orgBase(currentOrg!.id)}/alert-rules/${id}`, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alert-rules", currentOrg?.id] }),
  });
}

export function useDeleteRule() {
  const { currentOrg } = useOrg();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.del(`${orgBase(currentOrg!.id)}/alert-rules/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alert-rules", currentOrg?.id] }),
  });
}

export function useNotifications() {
  const { currentOrg } = useOrg();
  const orgId = currentOrg?.id;
  return useQuery({
    queryKey: ["notifications", orgId],
    queryFn: () => api.get<Notification[]>(`${orgBase(orgId!)}/notifications`),
    enabled: !!orgId,
  });
}

export function useUnreadCount() {
  const { currentOrg } = useOrg();
  const orgId = currentOrg?.id;
  return useQuery({
    queryKey: ["notifications", orgId, "unread"],
    queryFn: () => api.get<{ unread: number }>(`${orgBase(orgId!)}/notifications/unread-count`),
    enabled: !!orgId,
    refetchInterval: 60_000,
  });
}

export function useMarkRead() {
  const { currentOrg } = useOrg();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      api.post(`${orgBase(currentOrg!.id)}/notifications/${id}/read`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications", currentOrg?.id] }),
  });
}

export function useMarkAllRead() {
  const { currentOrg } = useOrg();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post(`${orgBase(currentOrg!.id)}/notifications/read-all`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications", currentOrg?.id] }),
  });
}
