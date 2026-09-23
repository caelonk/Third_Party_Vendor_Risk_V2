import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useVendorTrend } from "@/features/trends";

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

export function VendorTrendChart({ vendorId }: { vendorId: number }) {
  const { data, isLoading } = useVendorTrend(vendorId);
  if (isLoading)
    return <div className="empty"><span className="spinner" /></div>;

  const series = data ?? [];
  if (series.length < 2)
    return (
      <p className="subtle" style={{ fontSize: "0.85rem" }}>
        Not enough history yet — the risk trend appears once this vendor has been synced on more
        than one day.
      </p>
    );

  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={series} margin={{ top: 6, right: 8, left: -14, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
        <XAxis
          dataKey="captured_at"
          tickFormatter={shortDate}
          tick={{ fill: "var(--text-subtle)", fontSize: 11 }}
          stroke="var(--border)"
        />
        <YAxis
          yAxisId="cves"
          tick={{ fill: "var(--text-subtle)", fontSize: 11 }}
          stroke="var(--border)"
          width={34}
          allowDecimals={false}
        />
        <YAxis
          yAxisId="cvss"
          orientation="right"
          domain={[0, 10]}
          tick={{ fill: "var(--text-subtle)", fontSize: 11 }}
          stroke="var(--border)"
          width={28}
        />
        <Tooltip contentStyle={tooltipStyle} labelFormatter={(l) => shortDate(String(l))} />
        <Line
          yAxisId="cves"
          type="monotone"
          dataKey="cve_count"
          name="CVEs"
          stroke="var(--accent)"
          strokeWidth={2}
          dot={{ r: 2 }}
        />
        <Line
          yAxisId="cvss"
          type="monotone"
          dataKey="max_cvss"
          name="Max CVSS"
          stroke="var(--text-subtle)"
          strokeWidth={1.5}
          strokeDasharray="4 3"
          dot={false}
          connectNulls
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
