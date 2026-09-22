import type { CSSProperties } from "react";
import type { Tier } from "@/lib/types";

const SEV: Record<Tier, { c: string; fg: string }> = {
  Critical: { c: "var(--sev-critical)", fg: "var(--sev-critical-fg)" },
  High: { c: "var(--sev-high)", fg: "var(--sev-high-fg)" },
  Medium: { c: "var(--sev-medium)", fg: "var(--sev-medium-fg)" },
  Low: { c: "var(--sev-low)", fg: "var(--sev-low-fg)" },
  "Not Assessed": { c: "var(--sev-none)", fg: "var(--sev-none-fg)" },
};

/** Severity indicator — hue is always paired with the tier label, never alone. */
export function TierBadge({ tier, variant = "dot" }: { tier: Tier; variant?: "dot" | "fill" }) {
  const sev = SEV[tier];
  const style = { "--_c": sev.c, "--_fg": sev.fg } as CSSProperties;
  return (
    <span className={variant === "fill" ? "tier tier--fill" : "tier"} style={style}>
      <span className="tier__dot" aria-hidden />
      {tier}
    </span>
  );
}
