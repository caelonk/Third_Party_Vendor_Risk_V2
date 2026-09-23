export type Role = "owner" | "admin" | "member" | "viewer";
export type Theme = "light" | "dark" | "system";
export type Tier = "Critical" | "High" | "Medium" | "Low" | "Not Assessed";

export interface User {
  id: number;
  email: string;
  name: string | null;
  is_active: boolean;
  last_login_at: string | null;
}

export interface Org {
  id: number;
  name: string;
  slug: string;
  plan: string;
  created_at: string;
  role: Role;
}

export interface Member {
  user_id: number;
  email: string;
  name: string | null;
  role: Role;
}

export interface Invitation {
  id: number;
  email: string;
  role: Role;
  token: string;
  expires_at: string;
  accepted_at: string | null;
}

export interface Assessment {
  tier: Tier;
  threat_band: string | null;
  exposure_band: string | null;
  max_cvss: number | null;
  cve_count: number;
  kev_count: number;
}

export interface Vendor {
  id: number;
  name: string;
  cpe_prefix: string | null;
  match_method: string | null;
  is_mapped: boolean;
  annual_contract_value: number | null;
  data_sensitivity: string | null;
  business_criticality: string | null;
  contract_renewal_date: string | null;
  last_synced_at: string | null;
  assessment: Assessment;
}

export interface SyncRun {
  id: number;
  status: "running" | "success" | "partial" | "failed";
  vendors_attempted: number | null;
  vendors_succeeded: number | null;
  cves_upserted: number | null;
  error_detail: string | null;
  completed_at: string | null;
}

export type WidgetType =
  | "tier_distribution"
  | "risk_heatmap"
  | "watchlist"
  | "top_risk"
  | "kev_exposure"
  | "cve_trend";

export interface Widget {
  type: WidgetType;
  config: Record<string, unknown>;
  expanded: boolean;
  w: number;
  h: number;
}

export interface Preferences {
  theme: Theme;
  dashboard_layout: Widget[];
}

export interface DashboardSummary {
  vendor_count: number;
  mapped_count: number;
  tier_distribution: Record<string, number>;
  kev_exposed_vendors: number;
  total_cves: number;
}

export interface HeatmapCell {
  threat_band: string;
  exposure_band: string;
  tier: Tier;
  count: number;
  vendors: string[];
}

export interface WatchlistItem {
  vendor_id: number;
  vendor_name: string;
  tier: Tier;
  contract_renewal_date: string;
  days_until_renewal: number;
  max_cvss: number | null;
  kev_count: number;
}

export interface TopRiskItem {
  vendor_id: number;
  vendor_name: string;
  tier: Tier;
  max_cvss: number | null;
  cve_count: number;
  kev_count: number;
}

export interface VendorTrendPoint {
  captured_at: string;
  tier: Tier;
  max_cvss: number | null;
  cve_count: number;
  kev_count: number;
}

export interface PortfolioTrendPoint {
  date: string;
  total_cves: number;
  kev_vendors: number;
  tier_distribution: Record<string, number>;
}
