import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useOrg } from "@/org/OrgProvider";
import type { Invitation, Member, Role } from "@/lib/types";

export function useMembers() {
  const { currentOrg } = useOrg();
  const orgId = currentOrg?.id;
  return useQuery({
    queryKey: ["members", orgId],
    queryFn: () => api.get<Member[]>(`/orgs/${orgId}/members`),
    enabled: !!orgId,
  });
}

export function useInvitations(enabled: boolean) {
  const { currentOrg } = useOrg();
  const orgId = currentOrg?.id;
  return useQuery({
    queryKey: ["invitations", orgId],
    queryFn: () => api.get<Invitation[]>(`/orgs/${orgId}/invitations`),
    enabled: !!orgId && enabled,
  });
}

export function useCreateInvitation() {
  const { currentOrg } = useOrg();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: { email: string; role: Role }) =>
      api.post<Invitation>(`/orgs/${currentOrg!.id}/invitations`, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["invitations", currentOrg?.id] }),
  });
}

export function useSetMemberRole() {
  const { currentOrg } = useOrg();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, role }: { userId: number; role: Role }) =>
      api.patch<Member>(`/orgs/${currentOrg!.id}/members/${userId}`, { role }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["members", currentOrg?.id] }),
  });
}

/** Set the employee ID and team an org's admins keep for a member (blank clears). */
export function useUpdateMemberDetails() {
  const { currentOrg } = useOrg();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, ...details }: { userId: number; employee_id: string; team: string }) =>
      api.patch<Member>(`/orgs/${currentOrg!.id}/members/${userId}`, details),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["members", currentOrg?.id] });
      // Your own details are part of the org record the profile page reads.
      void qc.invalidateQueries({ queryKey: ["orgs"] });
    },
  });
}

export function useRemoveMember() {
  const { currentOrg } = useOrg();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (userId: number) => api.del(`/orgs/${currentOrg!.id}/members/${userId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["members", currentOrg?.id] }),
  });
}
