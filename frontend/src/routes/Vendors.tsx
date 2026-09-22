import { useState } from "react";
import { Plus, RefreshCw, ShieldAlert } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Modal } from "@/components/Modal";
import { TierBadge } from "@/components/TierBadge";
import { ApiError } from "@/lib/api";
import { fmtCvss, fmtRelative } from "@/lib/format";
import { useOrg } from "@/org/OrgProvider";
import {
  useCreateVendor,
  useSyncVendor,
  useVendors,
  type VendorInput,
} from "@/features/vendors";
import { VendorForm } from "./VendorForm";

export function Vendors() {
  const { currentOrg } = useOrg();
  const canWrite = currentOrg ? currentOrg.role !== "viewer" : false;
  const navigate = useNavigate();
  const { data: vendors, isLoading } = useVendors();
  const create = useCreateVendor();
  const sync = useSyncVendor();

  const [adding, setAdding] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const submit = (input: VendorInput) => {
    setFormError(null);
    create.mutate(input, {
      onSuccess: () => setAdding(false),
      onError: (e) => setFormError(e instanceof ApiError ? e.message : "Could not add vendor"),
    });
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Vendors</h1>
          <p>Third-party software you depend on, and its published-vulnerability exposure.</p>
        </div>
        {canWrite && (
          <button className="btn btn--primary" onClick={() => setAdding(true)}>
            <Plus /> Add vendor
          </button>
        )}
      </div>

      <div className="card">
        {isLoading ? (
          <div className="empty">
            <span className="spinner" />
          </div>
        ) : !vendors || vendors.length === 0 ? (
          <div className="empty">
            <ShieldAlert />
            <div>
              <strong>No vendors yet</strong>
              <p className="subtle" style={{ marginTop: 4 }}>
                Add the vendors you depend on to start scoring their risk.
              </p>
            </div>
            {canWrite && (
              <button className="btn btn--secondary" onClick={() => setAdding(true)}>
                <Plus /> Add your first vendor
              </button>
            )}
          </div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table className="table">
              <thead>
                <tr>
                  <th>Vendor</th>
                  <th>Tier</th>
                  <th className="num">Threat</th>
                  <th className="num">Exposure</th>
                  <th className="num">Max CVSS</th>
                  <th className="num">CVEs</th>
                  <th className="num">KEV</th>
                  <th>Last sync</th>
                  {canWrite && <th />}
                </tr>
              </thead>
              <tbody>
                {vendors.map((v) => {
                  const syncing = sync.isPending && sync.variables === v.id;
                  return (
                    <tr
                      key={v.id}
                      style={{ cursor: "pointer" }}
                      onClick={() => navigate(`/vendors/${v.id}`)}
                    >
                      <td>
                        <div style={{ fontWeight: 500 }}>{v.name}</div>
                        <div className="mono subtle" style={{ fontSize: "0.72rem" }}>
                          {v.cpe_prefix ?? "unmapped"}
                        </div>
                      </td>
                      <td>
                        <TierBadge tier={v.assessment.tier} />
                      </td>
                      <td className="num">{v.assessment.threat_band ?? "—"}</td>
                      <td className="num">{v.assessment.exposure_band ?? "—"}</td>
                      <td className="num">{fmtCvss(v.assessment)}</td>
                      <td className="num">{v.assessment.cve_count}</td>
                      <td className="num">{v.assessment.kev_count || "—"}</td>
                      <td className="subtle">{fmtRelative(v.last_synced_at)}</td>
                      {canWrite && (
                        <td onClick={(e) => e.stopPropagation()}>
                          <button
                            className="btn btn--ghost btn--sm"
                            disabled={syncing || !v.cpe_prefix}
                            title={v.cpe_prefix ? "Sync now" : "Map a CPE prefix to sync"}
                            onClick={() => sync.mutate(v.id)}
                          >
                            {syncing ? (
                              <span className="spinner" style={{ width: 14, height: 14 }} />
                            ) : (
                              <RefreshCw />
                            )}
                            Sync
                          </button>
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <Modal open={adding} onClose={() => setAdding(false)} title="Add vendor">
        <VendorForm submitting={create.isPending} error={formError} onSubmit={submit} />
      </Modal>
    </>
  );
}
