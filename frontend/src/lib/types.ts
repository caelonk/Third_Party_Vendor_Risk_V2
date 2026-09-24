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

export interface AuthProvider {
  id: string;
  name: string;
  /** The built-in development stand-in, not the real provider. */
  dev_stand_in: boolean;
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

export type AlertType = "new_kev" | "tier_change" | "renewal_due";
export type AlertChannel = "email" | "slack";

export interface AlertRule {
  id: number;
  type: AlertType;
  channel: AlertChannel;
  config: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
}

export interface Notification {
  id: number;
  type: AlertType;
  vendor_id: number | null;
  title: string;
  body: string | null;
  status: string;
  read_at: string | null;
  created_at: string;
}

export interface Integration {
  nvd_key_set: boolean;
  sync_cadence_hours: number;
}

export interface CpeCandidate {
  prefix: string;
  label: string;
  part: string;
  vendor: string;
  product: string;
  version_count: number;
  active: boolean;
}

export type SbomCandidateStatus = "new" | "exists" | "duplicate";

export interface SbomCandidate {
  name: string;
  cpe_prefix: string | null;
  versions: string[];
  component_count: number;
  supplier: string | null;
  status: SbomCandidateStatus;
}

export interface SbomPreview {
  format: "cyclonedx" | "spdx";
  spec_version: string | null;
  subject: string | null;
  component_count: number;
  candidates: SbomCandidate[];
}

export interface SbomImportResult {
  created: number;
  names: string[];
  skipped: { name: string; reason: "exists" | "invalid_cpe" | "empty_name" }[];
}

export interface AuditEntry {
  id: number;
  action: string;
  target_type: string | null;
  target_id: string | null;
  actor_email: string | null;
  actor_name: string | null;
  extra: Record<string, unknown> | null;
  created_at: string;
}

export type ExportFormat = "csv" | "pdf";
export type ExportStatus = "queued" | "running" | "succeeded" | "failed" | "expired";

export interface ExportJob {
  id: number;
  format: ExportFormat;
  status: ExportStatus;
  filename: string | null;
  size_bytes: number | null;
  error: string | null;
  requested_by: string | null;
  created_at: string;
  completed_at: string | null;
  expires_at: string | null;
}

export interface IntegrationUpdate {
  nvd_api_key?: string | null;
  sync_cadence_hours?: number;
}
