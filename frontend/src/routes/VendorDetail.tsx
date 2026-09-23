import { useState } from "react";
import { ArrowLeft, Pencil, RefreshCw, Trash2 } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Modal } from "@/components/Modal";
import { TierBadge } from "@/components/TierBadge";
import { VendorTrendChart } from "@/components/VendorTrendChart";
import { ApiError } from "@/lib/api";
import { fmtCvss, fmtDate, fmtMoney, fmtRelative } from "@/lib/format";
import { useOrg } from "@/org/OrgProvider";
import {
  useDeleteVendor,
  useSyncVendor,
  useUpdateVendor,
  useVendor,
  type VendorInput,
} from "@/features/vendors";
import { VendorForm } from "./VendorForm";
import "./vendor-detail.css";

const DISCLAIMER =
  'This tool measures published vulnerabilities in vendor products. It does not measure whether a vendor has been breached, the vendor’s internal security posture, or whether this organization is actually exposed. A high score means “investigate,” not “compromised.”';

function Stat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="stat">
      <div className="eyebrow">{label}</div>
      <div className="stat__value">{children}</div>
    </div>
  );
}

export function VendorDetail() {
  const { vendorId } = useParams();
  const id = Number(vendorId);
  const navigate = useNavigate();
  const { currentOrg } = useOrg();
  const canWrite = currentOrg ? currentOrg.role !== "viewer" : false;

  const { data: vendor, isLoading, isError } = useVendor(id);
  const sync = useSyncVendor();
  const update = useUpdateVendor(id);
  const del = useDeleteVendor();

  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  if (isLoading) return <div className="empty"><span className="spinner" /></div>;
  if (isError || !vendor)
    return (
      <div className="empty">
        <strong>Vendor not found</strong>
        <Link to="/vendors" className="btn btn--secondary">
          <ArrowLeft /> Back to vendors
        </Link>
      </div>
    );

  const a = vendor.assessment;
  const submitEdit = (input: VendorInput) => {
    setFormError(null);
    update.mutate(input, {
      onSuccess: () => setEditing(false),
      onError: (e) => setFormError(e instanceof ApiError ? e.message : "Could not save"),
    });
  };

  return (
    <>
      <Link to="/vendors" className="row subtle" style={{ marginBottom: "var(--space-4)", fontSize: "0.82rem" }}>
        <ArrowLeft size={15} /> Vendors
      </Link>

      <div className="page-header">
        <div className="row" style={{ gap: "var(--space-4)" }}>
          <h1 style={{ margin: 0 }}>{vendor.name}</h1>
          <TierBadge tier={a.tier} variant="fill" />
        </div>
        {canWrite && (
          <div className="row">
            <button
              className="btn btn--secondary"
              disabled={(sync.isPending && sync.variables === id) || !vendor.cpe_prefix}
              onClick={() => sync.mutate(id)}
              title={vendor.cpe_prefix ? "Sync now" : "Map a CPE prefix to sync"}
            >
              {sync.isPending && sync.variables === id ? (
                <span className="spinner" style={{ width: 14, height: 14 }} />
              ) : (
                <RefreshCw />
              )}
              Sync
            </button>
            <button className="btn btn--secondary" onClick={() => setEditing(true)}>
              <Pencil /> Edit
            </button>
            <button className="btn btn--danger" onClick={() => setConfirmDelete(true)}>
              <Trash2 />
            </button>
          </div>
        )}
      </div>

      <div className="vd__grid">
        <div className="card">
          <div className="card__header">
            <span className="card__title">Risk assessment</span>
            <span className="subtle" style={{ fontSize: "0.75rem" }}>
              synced {fmtRelative(vendor.last_synced_at)}
            </span>
          </div>
          <div className="card__body">
            <div className="vd__stats">
              <Stat label="Threat band">
                <span className="mono">{a.threat_band ?? "—"}</span>
              </Stat>
              <Stat label="Exposure band">
                <span className="mono">{a.exposure_band ?? "—"}</span>
              </Stat>
              <Stat label="Max CVSS">
                <span className="mono">{fmtCvss(a)}</span>
              </Stat>
              <Stat label="CVEs">
                <span className="mono">{a.cve_count}</span>
              </Stat>
              <Stat label="Known exploited">
                <span className="mono">{a.kev_count}</span>
              </Stat>
              <Stat label="Mapping">
                {vendor.is_mapped ? vendor.match_method ?? "mapped" : "not assessed"}
              </Stat>
            </div>
          </div>
        </div>

        <div className="card">
          <div className="card__header">
            <span className="card__title">Business context</span>
          </div>
          <div className="card__body">
            <div className="vd__stats">
              <Stat label="CPE prefix">
                <span className="mono" style={{ fontSize: "0.82rem" }}>
                  {vendor.cpe_prefix ?? "—"}
                </span>
              </Stat>
              <Stat label="Contract value">
                <span className="mono">{fmtMoney(vendor.annual_contract_value)}</span>
              </Stat>
              <Stat label="Data sensitivity">{vendor.data_sensitivity ?? "—"}</Stat>
              <Stat label="Criticality">{vendor.business_criticality ?? "—"}</Stat>
              <Stat label="Renewal">{fmtDate(vendor.contract_renewal_date)}</Stat>
            </div>
          </div>
        </div>
      </div>

      <div className="card" style={{ marginTop: "var(--space-5)" }}>
        <div className="card__header">
          <span className="card__title">Risk trend</span>
        </div>
        <div className="card__body">
          <VendorTrendChart vendorId={id} />
        </div>
      </div>

      <p className="vd__disclaimer">{DISCLAIMER}</p>

      <Modal open={editing} onClose={() => setEditing(false)} title={`Edit ${vendor.name}`}>
        <VendorForm
          vendor={vendor}
          submitting={update.isPending}
          error={formError}
          onSubmit={submitEdit}
          submitLabel="Save changes"
        />
      </Modal>

      <Modal open={confirmDelete} onClose={() => setConfirmDelete(false)} title="Delete vendor">
        <p className="muted" style={{ marginBottom: "var(--space-5)" }}>
          Remove <strong>{vendor.name}</strong> and its CVE links from this organization? This
          cannot be undone.
        </p>
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn btn--secondary" onClick={() => setConfirmDelete(false)}>
            Cancel
          </button>
          <button
            className="btn btn--danger"
            disabled={del.isPending}
            onClick={() =>
              del.mutate(id, { onSuccess: () => navigate("/vendors", { replace: true }) })
            }
          >
            {del.isPending ? <span className="spinner" style={{ width: 14, height: 14 }} /> : "Delete"}
          </button>
        </div>
      </Modal>
    </>
  );
}
