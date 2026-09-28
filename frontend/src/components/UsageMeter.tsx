import { meter } from "@/features/billing";
import "./billing.css";
import type { Usage } from "@/lib/types";

/** Usage against a plan limit. The fill is the accent color until the limit is
 *  reached, then danger; the state is always spelled out in the caption too, so
 *  it never relies on color alone. The track is a lighter step of the same hue. */
export function UsageMeter({ label, usage, note }: { label: string; usage: Usage; note?: string }) {
  const m = meter(usage);
  return (
    <div className={`meter meter--${m.state}`}>
      <div className="meter__head">
        <span className="meter__label">{label}</span>
        <span className="meter__caption">{m.caption}</span>
      </div>
      {m.state !== "unlimited" && (
        <div
          className="meter__track"
          role="meter"
          aria-label={label}
          aria-valuemin={0}
          aria-valuemax={usage.limit ?? 0}
          aria-valuenow={usage.used}
          aria-valuetext={m.caption}
        >
          <div className="meter__fill" style={{ width: `${Math.round(m.fraction * 100)}%` }} />
        </div>
      )}
      {note && <span className="meter__note">{note}</span>}
    </div>
  );
}
