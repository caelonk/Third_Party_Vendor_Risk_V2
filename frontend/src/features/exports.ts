import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useOrg } from "@/org/OrgProvider";
import type { ExportFormat, ExportJob } from "@/lib/types";

export const POLL_MS = 1500;

export const FORMAT_LABELS: Record<ExportFormat, string> = {
  csv: "CSV data",
  pdf: "PDF report",
};

// --------------------------------------------------------------------------- //
// Pure helpers (unit-tested)                                                  //
// --------------------------------------------------------------------------- //
export const isActive = (j: ExportJob) => j.status === "queued" || j.status === "running";

/** Poll only while something is still being prepared. */
export function pollInterval(jobs: ExportJob[] | undefined): number | false {
  return jobs?.some(isActive) ? POLL_MS : false;
}

/** Same-origin link that checks membership, then redirects to a fresh
 *  short-lived signed URL — so it never goes stale in the page. */
export function downloadPath(orgId: number, jobId: number): string {
  return `/api/v1/orgs/${orgId}/exports/${jobId}/download`;
}

export function fmtBytes(n: number | null): string {
  if (n == null) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(n < 10 * 1024 ? 1 : 0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

/** Of the jobs this tab is waiting on, which just became ready (download now)
 *  and which are done waiting (ready, failed, or expired). */
export function settleWaiting(jobs: ExportJob[], waiting: readonly number[]) {
  const ready: number[] = [];
  const settled: number[] = [];
  for (const j of jobs) {
    if (!waiting.includes(j.id) || isActive(j)) continue;
    settled.push(j.id);
    if (j.status === "succeeded") ready.push(j.id);
  }
  return { ready, settled };
}

// --------------------------------------------------------------------------- //
// API hooks                                                                   //
// --------------------------------------------------------------------------- //
export function useExports() {
  const { currentOrg } = useOrg();
  const orgId = currentOrg?.id;
  return useQuery({
    queryKey: ["exports", orgId],
    queryFn: () => api.get<ExportJob[]>(`/orgs/${orgId}/exports?limit=10`),
    enabled: !!orgId,
    refetchInterval: (query) => pollInterval(query.state.data),
  });
}

export function useCreateExport() {
  const { currentOrg } = useOrg();
  const qc = useQueryClient();
  const key = ["exports", currentOrg?.id];
  return useMutation({
    mutationFn: (format: ExportFormat) =>
      api.post<ExportJob>(`/orgs/${currentOrg!.id}/exports`, { format }),
    onSuccess: (job) => {
      // Show the new job immediately; polling takes it from here.
      qc.setQueryData<ExportJob[]>(key, (prev) => [job, ...(prev ?? []).filter((j) => j.id !== job.id)]);
    },
    onSettled: () => {
      // Also on failure: a job the server couldn't dispatch is listed as failed.
      qc.invalidateQueries({ queryKey: key });
      qc.invalidateQueries({ queryKey: ["audit-log", currentOrg?.id] });
    },
  });
}
