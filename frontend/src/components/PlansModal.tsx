import { Check } from "lucide-react";
import { Modal } from "@/components/Modal";
import { planFeatures, priceLabel, useOpenPortal, useStartCheckout } from "@/features/billing";
import type { BillingSummary, Plan } from "@/lib/types";
import { ErrorBanner } from "./ErrorBanner";
import "./billing.css";

function PlanAction({ plan, billing, canManage }: { plan: Plan; billing: BillingSummary; canManage: boolean }) {
  const checkout = useStartCheckout();
  const portal = useOpenPortal();
  const current = plan.id === billing.plan.id;

  if (current) return <span className="plan__current">Current plan</span>;
  if (!canManage || !billing.provider) return null;
  // With a subscription, every change (upgrade, downgrade, cancel) goes through
  // the billing portal, so the provider prorates it properly.
  if (billing.has_subscription) {
    return (
      <button className="btn btn--secondary btn--block" onClick={() => portal.mutate()} disabled={portal.isPending}>
        {plan.id === "free" ? "Cancel in billing portal" : "Change in billing portal"}
      </button>
    );
  }
  if (plan.id === "free") return null;
  return (
    <>
      <button
        className="btn btn--primary btn--block"
        onClick={() => checkout.mutate(plan.id as "team" | "business")}
        disabled={checkout.isPending}
      >
        {checkout.isPending ? <span className="spinner" /> : `Choose ${plan.name}`}
      </button>
      <ErrorBanner error={checkout.error} style={{ marginTop: "var(--space-2)" }} />
    </>
  );
}

export function PlansModal({
  open,
  onClose,
  billing,
  canManage,
}: {
  open: boolean;
  onClose: () => void;
  billing: BillingSummary;
  canManage: boolean;
}) {
  return (
    <Modal open={open} onClose={onClose} title="Compare plans" size="lg">
      <p className="subtle plans__intro">
        Demo pricing: billing runs in Stripe test mode and no real payment is ever taken.
        {!canManage && " Only an owner can change the plan."}
      </p>
      <div className="plans">
        {billing.plans.map((p) => (
          <div key={p.id} className={`plan${p.id === billing.plan.id ? " plan--current" : ""}`}>
            <div className="plan__name">{p.name}</div>
            <div className="plan__price">
              {priceLabel(p)}
              {p.price_usd_month > 0 && <span className="plan__demo"> demo</span>}
            </div>
            <ul className="plan__features">
              {planFeatures(p).map((f) => (
                <li key={f}>
                  <Check size={14} aria-hidden="true" /> {f}
                </li>
              ))}
            </ul>
            <PlanAction plan={p} billing={billing} canManage={canManage} />
          </div>
        ))}
      </div>
    </Modal>
  );
}
