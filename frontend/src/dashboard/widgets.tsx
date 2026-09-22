import { Fragment, type CSSProperties } from "react";
import { TierBadge } from "@/components/TierBadge";
import { fmtCvss, fmtDate } from "@/lib/format";
import { useHeatmap, useSummary, useTopRisk, useWatchlist } from "@/features/dashboard";
import type { Tier, WidgetType } from "@/lib/types";

const TIER_VAR: Record<Tier, string> = {
  Critical: "var(--sev-critical)",
  High: "var(--sev-high)",
  Medium: "var(--sev-medium)",
  Low: "var(--sev-low)",
  "Not Assessed": "var(--sev-none)",
};
const TIER_ORDER: Tier[] = ["Critical", "High", "Medium", "Low", "Not Assessed"];

function Loading() {
  return (
    <div style={{ display: "grid", placeItems: "center", minHeight: 90 }}>
      <span className="spinner" />
    </div>
  );
}

/* -------------------------------------------------------- Tier distribution */
function TierDistribution({ expanded }: { expanded: boolean }) {
  const { data, isLoading } = useSummary();
  if (isLoading) return <Loading />;
  const dist = data?.tier_distribution ?? {};
  const total = Object.values(dist).reduce((a, b) => a + b, 0);
  const segments = TIER_ORDER.map((t) => ({ tier: t, count: dist[t] ?? 0 })).filter((s) => s.count);

  if (total === 0) return <p className="subtle">No vendors scored yet.</p>;

  return (
    <div>
      <div className="wbar">
        {segments.map((s) => (
          <div
            key={s.tier}
            className="wbar__seg"
            style={{ flex: s.count, background: TIER_VAR[s.tier] } as CSSProperties}
            title={`${s.tier}: ${s.count}`}
          />
        ))}
      </div>
      {expanded ? (
        <div className="wlist">
          {TIER_ORDER.map((t) => (
            <div key={t} className="wlist__row">
              <TierBadge tier={t} />
              <span className="mono">{dist[t] ?? 0}</span>
              <span className="subtle mono" style={{ fontSize: "0.75rem" }}>
                {total ? Math.round(((dist[t] ?? 0) / total) * 100) : 0}%
              </span>
            </div>
          ))}
        </div>
      ) : (
        <div className="wbar__legend">
          {segments.map((s) => (
            <span key={s.tier} className="tier">
              <span className="tier__dot" style={{ background: TIER_VAR[s.tier] } as CSSProperties} />
              {s.count}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------- Risk heatmap */
function RiskHeatmap({ expanded }: { expanded: boolean }) {
  const { data, isLoading } = useHeatmap();
  if (isLoading) return <Loading />;
  const cells = data?.cells ?? [];
  const exposures = ["E1", "E2", "E3", "E4"];
  const threats = ["T4", "T3", "T2", "T1"];
  const at = (t: string, e: string) => cells.find((c) => c.threat_band === t && c.exposure_band === e);

  return (
    <div className={`heat${expanded ? " heat--lg" : ""}`}>
      <div className="heat__grid">
        <span />
        {exposures.map((e) => (
          <span key={e} className="heat__axis">
            {e}
          </span>
        ))}
        {threats.map((t) => (
          <Fragment key={t}>
            <span className="heat__axis">{t}</span>
            {exposures.map((e) => {
              const cell = at(t, e);
              const count = cell?.count ?? 0;
              const style = {
                background: count ? TIER_VAR[cell!.tier] : "var(--sev-empty)",
                color: count ? "#fff" : "var(--text-subtle)",
              } as CSSProperties;
              return (
                <div
                  key={`${t}-${e}`}
                  className="heat__cell"
                  style={style}
                  title={count ? `${cell!.tier} — ${cell!.vendors.join(", ")}` : "no vendors"}
                >
                  <span className="mono heat__count">{count || ""}</span>
                  {expanded && count > 0 && <span className="heat__tier">{cell!.tier}</span>}
                </div>
              );
            })}
          </Fragment>
        ))}
      </div>
      {expanded && (
        <p className="subtle" style={{ fontSize: "0.75rem", marginTop: "var(--space-3)" }}>
          Threat (rows, T4 highest) &times; exposure (columns, E4 highest). Tint follows the final
          tier, not a formula.
        </p>
      )}
    </div>
  );
}

/* --------------------------------------------------------------- Watchlist */
function Watchlist({ expanded }: { expanded: boolean }) {
  const { data, isLoading } = useWatchlist();
  if (isLoading) return <Loading />;
  const items = data ?? [];
  if (items.length === 0)
    return <p className="subtle">No High/Critical vendors renewing in the next 90 days.</p>;

  const shown = expanded ? items : items.slice(0, 3);
  return (
    <div className="wlist">
      {shown.map((it) => (
        <div key={it.vendor_id} className="wlist__row wlist__row--wide">
          <span style={{ flex: 1, fontWeight: 500 }}>{it.vendor_name}</span>
          <TierBadge tier={it.tier} />
          <span className="mono subtle" style={{ fontSize: "0.78rem" }}>
            {it.days_until_renewal}d
          </span>
          {expanded && <span className="subtle" style={{ fontSize: "0.78rem" }}>{fmtDate(it.contract_renewal_date)}</span>}
        </div>
      ))}
      {!expanded && items.length > 3 && (
        <span className="subtle" style={{ fontSize: "0.78rem" }}>
          +{items.length - 3} more
        </span>
      )}
    </div>
  );
}

/* -------------------------------------------------------------- Top risk */
function TopRisk({ expanded }: { expanded: boolean }) {
  const { data, isLoading } = useTopRisk();
  if (isLoading) return <Loading />;
  const items = (data ?? []).filter((i) => i.tier !== "Not Assessed");
  if (items.length === 0) return <p className="subtle">No scored vendors yet.</p>;
  const shown = expanded ? items : items.slice(0, 3);
  return (
    <div className="wlist">
      {shown.map((it) => (
        <div key={it.vendor_id} className="wlist__row wlist__row--wide">
          <span style={{ flex: 1, fontWeight: 500 }}>{it.vendor_name}</span>
          <TierBadge tier={it.tier} />
          <span className="mono" style={{ fontSize: "0.78rem" }}>
            {fmtCvss(it)}
          </span>
          {expanded && it.kev_count > 0 && <span className="pill pill--kev">KEV {it.kev_count}</span>}
        </div>
      ))}
    </div>
  );
}

/* ----------------------------------------------------------- KEV exposure */
function KevExposure({ expanded }: { expanded: boolean }) {
  const { data, isLoading } = useSummary();
  if (isLoading) return <Loading />;
  const kev = data?.kev_exposed_vendors ?? 0;
  const total = data?.vendor_count ?? 0;
  return (
    <div>
      <div className="wbig">
        <span className="wbig__num mono">{kev}</span>
        <span className="subtle">
          {kev === 1 ? "vendor" : "vendors"} with known-exploited CVEs
        </span>
      </div>
      {expanded && (
        <div className="wlist" style={{ marginTop: "var(--space-4)" }}>
          <div className="wlist__row">
            <span className="subtle">Share of portfolio</span>
            <span className="mono">{total ? Math.round((kev / total) * 100) : 0}%</span>
          </div>
          <div className="wlist__row">
            <span className="subtle">CVEs tracked</span>
            <span className="mono">{data?.total_cves ?? 0}</span>
          </div>
        </div>
      )}
    </div>
  );
}

export const WIDGET_COMPONENTS: Record<
  WidgetType,
  (props: { expanded: boolean }) => JSX.Element
> = {
  tier_distribution: TierDistribution,
  risk_heatmap: RiskHeatmap,
  watchlist: Watchlist,
  top_risk: TopRisk,
  kev_exposure: KevExposure,
  data_health: KevExposure, // reserved; not offered in the catalog
};
