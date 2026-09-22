import { Activity, Flame, Grid3x3, ListChecks, TrendingUp } from "lucide-react";
import type { WidgetType } from "@/lib/types";

export interface CatalogEntry {
  type: WidgetType;
  title: string;
  description: string;
  icon: typeof Activity;
}

/** The widgets a user can add. The 5-widget cap is enforced against this. */
export const CATALOG: CatalogEntry[] = [
  {
    type: "tier_distribution",
    title: "Tier distribution",
    description: "How your portfolio splits across risk tiers.",
    icon: Activity,
  },
  {
    type: "risk_heatmap",
    title: "Risk heatmap",
    description: "Threat x exposure matrix at a glance.",
    icon: Grid3x3,
  },
  {
    type: "watchlist",
    title: "Renewal watchlist",
    description: "High/Critical vendors renewing soon.",
    icon: ListChecks,
  },
  {
    type: "top_risk",
    title: "Top-risk vendors",
    description: "Your highest-scoring vendors.",
    icon: TrendingUp,
  },
  {
    type: "kev_exposure",
    title: "KEV exposure",
    description: "Vendors with known-exploited CVEs.",
    icon: Flame,
  },
];

export const TITLES = Object.fromEntries(CATALOG.map((c) => [c.type, c.title])) as Record<
  WidgetType,
  string
>;
