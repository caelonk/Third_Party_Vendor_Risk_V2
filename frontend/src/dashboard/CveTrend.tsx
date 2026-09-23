import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { usePortfolioTrend } from "@/features/trends";

function shortDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

const tooltipStyle = {
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: "8px",
  fontSize: "0.75rem",
  color: "var(--text)",
  boxShadow: "var(--shadow)",
};

export function CveTrend({ expanded }: { expanded: boolean }) {
  const { data, isLoading } = usePortfolioTrend();
  if (isLoading)
    return (
      <div style={{ display: "grid", placeItems: "center", minHeight: 90 }}>
        <span className="spinner" />
      </div>
    );

  const series = data ?? [];
  if (series.length < 2)
    return (
      <div>
        {series.length === 1 && (
          <div className="wbig">
            <span className="wbig__num mono">{series[0].total_cves}</span>
            <span className="subtle">CVEs tracked</span>
          </div>
        )}
        <p className="subtle" style={{ fontSize: "0.78rem", marginTop: "var(--space-2)" }}>
          Trend lines appear once vendors have been synced on more than one day.
        </p>
      </div>
    );

  return (
    <div style={{ marginTop: 4 }}>
      <ResponsiveContainer width="100%" height={expanded ? 200 : 96}>
        <AreaChart data={series} margin={{ top: 4, right: 4, left: -18, bottom: 0 }}>
          {expanded && <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />}
          <XAxis
            dataKey="date"
            tickFormatter={shortDate}
            tick={{ fill: "var(--text-subtle)", fontSize: 11 }}
            stroke="var(--border)"
            hide={!expanded}
          />
          <YAxis
            tick={{ fill: "var(--text-subtle)", fontSize: 11 }}
            stroke="var(--border)"
            width={34}
            allowDecimals={false}
            hide={!expanded}
          />
          <Tooltip
            contentStyle={tooltipStyle}
            labelFormatter={(l) => shortDate(String(l))}
            formatter={(v: number) => [v, "CVEs"]}
          />
          <Area
            type="monotone"
            dataKey="total_cves"
            stroke="var(--accent)"
            strokeWidth={2}
            fill="var(--accent)"
            fillOpacity={0.12}
          />
        </AreaChart>
      </ResponsiveContainer>
      {expanded && (
        <p className="subtle" style={{ fontSize: "0.75rem", marginTop: "var(--space-2)" }}>
          Total tracked CVEs across the portfolio over time.
        </p>
      )}
    </div>
  );
}
