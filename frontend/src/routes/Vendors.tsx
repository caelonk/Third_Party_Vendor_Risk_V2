import { useMemo, useState } from "react";
import { FileJson, Plus, RefreshCw, SearchX, ShieldAlert } from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Modal } from "@/components/Modal";
import { SbomImport } from "@/components/SbomImport";
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
import {
  DEFAULT_FILTERS,
  applyFilters,
  filtersToParams,
  nextSort,
  parseFilters,
  sortVendors,
  type SortKey,
  type VendorFilters,
} from "@/features/vendorFilters";
import { VendorForm } from "./VendorForm";
import { SortHeader, VendorToolbar } from "./VendorToolbar";

export function Vendors() {
  const { currentOrg } = useOrg();
  const canWrite = currentOrg ? currentOrg.role !== "viewer" : false;
  const navigate = useNavigate();
  const { data: vendors, isLoading } = useVendors();
  const create = useCreateVendor();
  const sync = useSyncVendor();

  const [adding, setAdding] = useState(false);
  const [importing, setImporting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // Filter/sort state lives in the URL: shareable, and survives refresh + back.
  const [params, setParams] = useSearchParams();
  const filters = useMemo(() => parseFilters(params), [params]);
  const setFilters = (next: VendorFilters) => setParams(filtersToParams(next), { replace: true });
  const update = (patch: Partial<VendorFilters>) => setFilters({ ...filters, ...patch });
  const onSort = (key: SortKey) => update(nextSort(filters, key));
  const clearFilters = () => setFilters({ ...DEFAULT_FILTERS, sort: filters.sort, dir: filters.dir });

  const visible = useMemo(
    () => sortVendors(applyFilters(vendors ?? [], filters), filters.sort, filters.dir),
    [vendors, filters],
  );

  const submit = (input: VendorInput) => {
    setFormError(null);
    create.mutate(input, {
      onSuccess: () => setAdding(false),
      onError: (e) => setFormError(e instanceof ApiError ? e.message : "Could not add vendor"),
    });
  };

  const sortProps = { filters, onSort };

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Vendors</h1>
          <p>Third-party software you depend on, and its published-vulnerability exposure.</p>
        </div>
        {canWrite && (
          <div className="page-header__actions">
            <button className="btn btn--secondary" onClick={() => setImporting(true)}>
              <FileJson /> Import SBOM
            </button>
            <button className="btn btn--primary" onClick={() => setAdding(true)}>
              <Plus /> Add vendor
            </button>
          </div>
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
              <div className="page-header__actions" style={{ justifyContent: "center" }}>
                <button className="btn btn--secondary" onClick={() => setAdding(true)}>
                  <Plus /> Add your first vendor
                </button>
                <button className="btn btn--secondary" onClick={() => setImporting(true)}>
                  <FileJson /> Import an SBOM
                </button>
              </div>
            )}
          </div>
        ) : (
          <>
            <VendorToolbar
              filters={filters}
              onChange={update}
              onClear={clearFilters}
              shown={visible.length}
              total={vendors.length}
            />
            {visible.length === 0 ? (
              <div className="empty">
                <SearchX />
                <div>
                  <strong>No vendors match these filters</strong>
                  <p className="subtle" style={{ marginTop: 4 }}>
                    Try a different search, or clear the filters to see all {vendors.length}.
                  </p>
                </div>
                <button className="btn btn--secondary" onClick={clearFilters}>
                  Clear filters
                </button>
              </div>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table className="table">
                  <thead>
                    <tr>
                      <SortHeader label="Vendor" sortKey="name" {...sortProps} />
                      <SortHeader label="Tier" sortKey="tier" {...sortProps} />
                      <th className="num">Threat</th>
                      <th className="num">Exposure</th>
                      <SortHeader label="Max CVSS" sortKey="max_cvss" num {...sortProps} />
                      <SortHeader label="CVEs" sortKey="cves" num {...sortProps} />
                      <SortHeader label="KEV" sortKey="kev" num {...sortProps} />
                      <SortHeader label="Last sync" sortKey="last_sync" {...sortProps} />
                      {canWrite && <th />}
                    </tr>
                  </thead>
                  <tbody>
                    {visible.map((v) => {
                      const syncing = sync.isPending && sync.variables === v.id;
                      const assessed = v.assessment.tier !== "Not Assessed";
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
                          {/* Unassessed counts are unknown, not zero. */}
                          <td className="num">{assessed ? v.assessment.cve_count : "—"}</td>
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
          </>
        )}
      </div>

      <Modal open={adding} onClose={() => setAdding(false)} title="Add vendor">
        <VendorForm submitting={create.isPending} error={formError} onSubmit={submit} />
      </Modal>

      <Modal open={importing} onClose={() => setImporting(false)} title="Import from SBOM" size="lg">
        <SbomImport onDone={() => setImporting(false)} />
      </Modal>
    </>
  );
}
