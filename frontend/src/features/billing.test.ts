import { describe, expect, it } from "vitest";
import { ApiError } from "@/lib/api";
import type { Plan } from "@/lib/types";
import { isPlanLimit, meter, planFeatures, priceLabel, statusLabel } from "./billing";

const plan = (over: Partial<Plan> = {}): Plan => ({
  id: "free",
  name: "Free",
  price_usd_month: 0,
  max_vendors: 10,
  max_members: 3,
  min_sync_hours: 24,
  pdf_reports: false,
  ...over,
});

describe("meter", () => {
  it("says how much room is left while under the limit", () => {
    expect(meter({ used: 8, limit: 10 })).toEqual({ state: "ok", fraction: 0.8, caption: "8 of 10 · 2 left" });
  });

  it("flags the limit and anything over it (after a downgrade)", () => {
    expect(meter({ used: 10, limit: 10 }).state).toBe("full");
    const over = meter({ used: 20, limit: 10 });
    expect(over.state).toBe("over");
    expect(over.fraction).toBe(1); // the bar never draws past its track
    expect(over.caption).toMatch(/over the limit/);
  });

  it("has no fill for unlimited plans", () => {
    expect(meter({ used: 12, limit: null })).toEqual({ state: "unlimited", fraction: 0, caption: "12 · unlimited" });
  });
});

describe("plan copy", () => {
  it("lists what each plan includes", () => {
    expect(planFeatures(plan())).toEqual([
      "Up to 10 vendors",
      "Up to 3 members",
      "Auto-sync every 24h",
      "CSV exports",
    ]);
    const biz = plan({ max_vendors: 1000, max_members: null, min_sync_hours: 1, pdf_reports: true });
    expect(planFeatures(biz)).toEqual([
      "Up to 1,000 vendors",
      "Unlimited members",
      "Hourly auto-sync",
      "CSV + PDF reports",
    ]);
    expect(priceLabel(plan())).toBe("$0");
    expect(priceLabel(plan({ price_usd_month: 49 }))).toBe("$49/mo");
  });

  it("labels subscription state honestly", () => {
    expect(statusLabel({ status: "past_due", has_subscription: true, plan: plan({ id: "team" }) })).toBe(
      "Payment past due",
    );
    expect(statusLabel({ status: null, has_subscription: false, plan: plan() })).toBe("No subscription");
    // e.g. a demo org put on Business directly, with no Stripe subscription behind it
    expect(statusLabel({ status: null, has_subscription: false, plan: plan({ id: "business" }) })).toBe(
      "Assigned plan",
    );
  });
});

describe("isPlanLimit", () => {
  it("is true only for a 402", () => {
    expect(isPlanLimit(new ApiError(402, "Upgrade"))).toBe(true);
    expect(isPlanLimit(new ApiError(403, "No"))).toBe(false);
    expect(isPlanLimit(new Error("x"))).toBe(false);
  });
});
