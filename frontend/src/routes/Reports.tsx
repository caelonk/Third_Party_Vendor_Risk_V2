import { type ReactNode, useEffect, useState } from "react";
import { Download, FileSpreadsheet, FileText, ScrollText } from "lucide-react";
import { fmtDate, fmtRelative } from "@/lib/format";
import { useOrg } from "@/org/OrgProvider";
import { useAuditLog } from "@/features/audit";
import {
  FORMAT_LABELS,
  downloadPath,
  fmtBytes,
  isActive,
  settleWaiting,
  useCreateExport,
  useExports,
} from "@/features/exports";
import type { AuditEntry, ExportFormat, ExportJob } from "@/lib/types";
import "./reports.css";

const ACTION_LABELS: Record<string, string> = {
  "vendor.created": "Created vendor",
  "vendor.updated": "Updated vendor",
  "vendor.deleted": "Deleted vendor",
  "vendor.synced": "Synced vendor",
  "vendor.imported": "Imported vendors",
  "export.requested": "Requested export",
  "member.invited": "Invited member",
  "member.role_changed": "Changed member role",
  "member.removed": "Removed member",
  "integration.updated": "Updated sync settings",
};

function detail(e: AuditEntry): string {
  const x = e.extra ?? {};
  if (typeof x.name === "string") return x.name;
  if (typeof x.email === "string") return x.email;
  if (Array.isArray(x.fields)) return (x.fields as string[]).join(", ");
  if (typeof x.status === "string") return String(x.status);
  if (typeof x.format === "string") return FORMAT_LABELS[x.format as ExportFormat] ?? x.format;
  if (typeof x.created === "number") {
    return `${x.created} added${x.source === "sbom" ? " from SBOM" : ""}`;
  }
  return e.target_type ? `${e.target_type} ${e.target_id ?? ""}`.trim() : "—";
}

function ActivityLog() {
  const { currentOrg } = useOrg();
  const canView = currentOrg ? ["owner", "admin"].includes(currentOrg.role) : false;
  const log = useAuditLog(canView);

  if (!canView) return null;
  const entries = log.data ?? [];

  return (
    <section className="card">
      <div className="card__header">
        <span className="card__title">Activity log</span>
      </div>
      <div className="card__body" style={{ padding: 0 }}>
        {entries.length === 0 ? (
          <div className="empty">
            <ScrollText />
            <p className="subtle">No recorded activity yet.</p>
          </div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>When</th>
                <th>Who</th>
                <th>Action</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.id}>
                  <td className="subtle" style={{ whiteSpace: "nowrap" }}>
                    {fmtRelative(e.created_at)}
                  </td>
                  <td>{e.actor_name ?? e.actor_email ?? "System"}</td>
                  <td>{ACTION_LABELS[e.action] ?? e.action}</td>
                  <td className="subtle">{detail(e)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}

function JobAction({ orgId, job }: { orgId: number; job: ExportJob }) {
  if (isActive(job)) {
    return (
      <span className="exports__state">
        <span className="spinner exports__spinner" /> Preparing
      </span>
    );
  }
  if (job.status === "succeeded") {
    return (
      <a className="btn btn--secondary btn--sm" href={downloadPath(orgId, job.id)}>
        <Download size={14} /> Download
      </a>
    );
  }
  return <span className="pill">{job.status === "failed" ? "Failed" : "Expired"}</span>;
}

function ExportPanel() {
  const { currentOrg } = useOrg();
  const exportsQ = useExports();
  const create = useCreateExport();
  // Jobs requested from this tab: each downloads automatically once ready.
  const [waiting, setWaiting] = useState<number[]>([]);
  const jobs = exportsQ.data ?? [];

  useEffect(() => {
    if (!currentOrg || waiting.length === 0) return;
    const { ready, settled } = settleWaiting(jobs, waiting);
    if (settled.length === 0) return;
    setWaiting((w) => w.filter((id) => !settled.includes(id)));
    // One navigation at a time; anything else that finished is in the list below.
    if (ready.length) window.location.assign(downloadPath(currentOrg.id, ready[0]));
  }, [jobs, waiting, currentOrg]);

  if (!currentOrg) return null;

  const busy = (format: ExportFormat) =>
    (create.isPending && create.variables === format) ||
    jobs.some((j) => j.format === format && isActive(j) && waiting.includes(j.id));

  const start = (format: ExportFormat) =>
    create.mutate(format, { onSuccess: (job) => setWaiting((w) => [...w, job.id]) });

  const button = (format: ExportFormat, icon: ReactNode, label: string) => (
    <button
      type="button"
      className="btn btn--secondary"
      disabled={busy(format)}
      onClick={() => start(format)}
    >
      {busy(format) ? <span className="spinner exports__spinner" /> : icon}
      {busy(format) ? `Preparing ${FORMAT_LABELS[format]}…` : label}
    </button>
  );

  return (
    <section className="card">
      <div className="card__header">
        <span className="card__title">Export portfolio</span>
      </div>
      <div className="card__body">
        <p className="subtle" style={{ marginTop: 0, fontSize: "0.85rem" }}>
          A snapshot of every vendor with its current tier, threat and exposure bands, max CVSS,
          CVE and KEV counts, and business context. Unscored vendors export blank — never a
          fabricated 0.0.
        </p>

        <div className="reports__actions">
          {button("csv", <FileSpreadsheet size={16} />, "Export CSV")}
          {button("pdf", <FileText size={16} />, "Export PDF report")}
        </div>

        {create.isError && (
          <div className="banner banner--error" role="alert" style={{ marginBottom: "var(--space-4)" }}>
            {create.error.message}
          </div>
        )}

        {jobs.length > 0 && (
          <div className="exports">
            <div className="exports__heading">Recent exports</div>
            <ul className="exports__list">
              {jobs.map((j) => (
                <li key={j.id} className="exports__item">
                  <div className="exports__main">
                    <span className="exports__name">{FORMAT_LABELS[j.format]}</span>
                    <span className="subtle exports__meta">
                      {fmtRelative(j.created_at)}
                      {j.requested_by ? ` · ${j.requested_by}` : ""}
                      {j.status === "succeeded" && ` · ${fmtBytes(j.size_bytes)}`}
                      {j.status === "succeeded" && j.expires_at && ` · until ${fmtDate(j.expires_at)}`}
                    </span>
                    {j.status === "failed" && j.error && (
                      <span className="exports__error">{j.error}</span>
                    )}
                  </div>
                  <JobAction orgId={currentOrg.id} job={j} />
                </li>
              ))}
            </ul>
          </div>
        )}

        <p className="subtle reports__note">
          Exports are prepared in the background and kept for a limited time; each download uses a
          private link that expires within minutes. Every export carries the scope disclaimer
          verbatim: a high score means “investigate,” not “compromised.”
        </p>
      </div>
    </section>
  );
}

export function Reports() {
  return (
    <>
      <div className="page-header">
        <div>
          <h1>Reports</h1>
          <p>Export your vendor portfolio and review recorded account activity.</p>
        </div>
      </div>

      <div className="reports">
        <ExportPanel />
        <ActivityLog />
      </div>
    </>
  );
}
