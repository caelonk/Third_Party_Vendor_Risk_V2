import type { Assessment } from "./types";

/** Honest-data display: a CVE with no CVSS is "Unscored", never 0.0. */
export function fmtCvss(a: Pick<Assessment, "max_cvss" | "cve_count">): string {
  if (a.max_cvss != null) return a.max_cvss.toFixed(1);
  return a.cve_count > 0 ? "Unscored" : "—";
}

export function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function fmtRelative(iso: string | null): string {
  if (!iso) return "never";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "never";
  const s = Math.round((Date.now() - then) / 1000);
  if (s < 60) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.round(h / 24);
  if (d < 30) return `${d}d ago`;
  return fmtDate(iso);
}

export function fmtMoney(v: number | null): string {
  if (v == null) return "—";
  return v.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}
