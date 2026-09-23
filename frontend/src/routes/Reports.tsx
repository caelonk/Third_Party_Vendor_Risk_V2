import { FileSpreadsheet, FileText, ScrollText } from "lucide-react";
import { fmtRelative } from "@/lib/format";
import { useOrg } from "@/org/OrgProvider";
import { useAuditLog } from "@/features/audit";
import type { AuditEntry } from "@/lib/types";
import "./reports.css";

const ACTION_LABELS: Record<string, string> = {
  "vendor.created": "Created vendor",
  "vendor.updated": "Updated vendor",
  "vendor.deleted": "Deleted vendor",
  "vendor.synced": "Synced vendor",
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

export function Reports() {
  const { currentOrg } = useOrg();
  const base = currentOrg ? `/api/v1/orgs/${currentOrg.id}/export` : "#";

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Reports</h1>
          <p>Export your vendor portfolio and review recorded account activity.</p>
        </div>
      </div>

      <div className="reports">
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
              <a className="btn btn--secondary" href={`${base}/vendors.csv`}>
                <FileSpreadsheet size={16} /> Export CSV
              </a>
              <a className="btn btn--secondary" href={`${base}/portfolio.pdf`}>
                <FileText size={16} /> Export PDF report
              </a>
            </div>

            <p className="subtle reports__note">
              Every export carries the scope disclaimer verbatim: a high score means “investigate,”
              not “compromised.”
            </p>
          </div>
        </section>

        <ActivityLog />
      </div>
    </>
  );
}
