import { FileSpreadsheet, FileText } from "lucide-react";
import { useOrg } from "@/org/OrgProvider";
import "./reports.css";

export function Reports() {
  const { currentOrg } = useOrg();
  const base = currentOrg ? `/api/v1/orgs/${currentOrg.id}/export` : "#";

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Reports</h1>
          <p>Export your vendor portfolio for spreadsheets or audit-ready sharing.</p>
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
      </div>
    </>
  );
}
