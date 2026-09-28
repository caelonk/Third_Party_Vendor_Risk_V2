import { useEffect, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { CreditCard } from "lucide-react";
import { ErrorBanner } from "@/components/ErrorBanner";
import { PlansModal } from "@/components/PlansModal";
import { UsageMeter } from "@/components/UsageMeter";
import { planFeatures, priceLabel, statusLabel, useBilling, useOpenPortal } from "@/features/billing";
import { fmtDate } from "@/lib/format";
import type { BillingSummary } from "@/lib/types";

const PROVIDER_NOTES: Record<string, string> = {
  stripe_test:
    "Stripe test mode: use card 4242 4242 4242 4242 with any future date and CVC. No real charges.",
  dev_stand_in:
    "Development stand-in: no Stripe account is configured, so checkout and the billing portal are simulated.",
};

function Notices({ billing }: { billing: BillingSummary }) {
  if (billing.status === "past_due" && billing.has_subscription) {
    return (
      <div className="banner banner--error" role="alert">
        The last payment for {billing.plan.name} failed. It will be retried; update the payment
        method in the billing portal to keep the plan.
      </div>
    );
  }
  if (billing.cancel_at_period_end && billing.current_period_end) {
    return (
      <div className="banner">
        {billing.plan.name} ends on {fmtDate(billing.current_period_end)}; the organization then
        moves to Free. Nothing is deleted.
      </div>
    );
  }
  return null;
}

export function BillingCard({ canManage }: { canManage: boolean }) {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  // Coming back from checkout: the webhook may land a moment after the
  // redirect, so poll briefly until the subscription shows up.
  const [returned] = useState(() => params.get("billing"));
  const [confirming, setConfirming] = useState(returned === "success");
  const billing = useBilling({ pollMs: confirming ? 2000 : false });
  const portal = useOpenPortal();
  const [plansOpen, setPlansOpen] = useState(false);

  useEffect(() => {
    if (!params.has("billing")) return;
    // Drop the one-shot flag but keep the #billing anchor (the page scrolls to it).
    const rest = new URLSearchParams(params);
    rest.delete("billing");
    const search = rest.toString();
    navigate({ search: search ? `?${search}` : "", hash: location.hash }, { replace: true });
  }, [params, navigate, location.hash]);

  useEffect(() => {
    if (!confirming) return;
    if (billing.data?.has_subscription) setConfirming(false);
    const giveUp = setTimeout(() => setConfirming(false), 20_000);
    return () => clearTimeout(giveUp);
  }, [confirming, billing.data?.has_subscription]);

  if (!billing.data) return null;
  const b = billing.data;
  const note = b.provider ? PROVIDER_NOTES[b.provider] : null;

  return (
    <section className="card" id="billing">
      <div className="card__header">
        <span className="card__title">Plan &amp; billing</span>
      </div>
      <div className="card__body billing">
        {returned === "success" &&
          (confirming ? (
            <div className="banner" role="status">
              <span className="spinner billing__spinner" /> Confirming your subscription…
            </div>
          ) : b.has_subscription ? (
            <div className="banner banner--ok" role="status">
              Subscription confirmed: you're on {b.plan.name}.
            </div>
          ) : (
            <div className="banner" role="status">
              Checkout finished, but the subscription hasn't been confirmed yet. Refresh in a
              moment.
            </div>
          ))}
        {returned === "cancelled" && (
          <div className="banner" role="status">
            Checkout was cancelled. Nothing changed.
          </div>
        )}
        <Notices billing={b} />

        <div className="billing__plan">
          <div>
            <div className="billing__plan-name">
              {b.plan.name}
              <span className="billing__price">{priceLabel(b.plan)}</span>
            </div>
            <div className="subtle billing__status">
              {statusLabel(b)}
              {b.has_subscription && b.current_period_end && !b.cancel_at_period_end &&
                ` · renews ${fmtDate(b.current_period_end)}`}
            </div>
          </div>
          <div className="billing__actions">
            <button type="button" className="btn btn--secondary btn--sm" onClick={() => setPlansOpen(true)}>
              Compare plans
            </button>
            {canManage && b.has_billing_account && b.provider && (
              <button
                type="button"
                className="btn btn--secondary btn--sm"
                onClick={() => portal.mutate()}
                disabled={portal.isPending}
              >
                <CreditCard size={14} /> Manage billing
              </button>
            )}
          </div>
        </div>
        <ErrorBanner error={portal.error} />

        <div className="billing__meters">
          <UsageMeter label="Vendors" usage={b.vendors} />
          <UsageMeter
            label="Seats"
            usage={b.members}
            note={b.members_pending ? `Includes ${b.members_pending} pending invitation${b.members_pending === 1 ? "" : "s"}.` : undefined}
          />
        </div>

        <p className="subtle billing__features">{planFeatures(b.plan).slice(2).join(" · ")}</p>

        {!canManage && <p className="subtle billing__hint">Only an owner can change the plan.</p>}
        {!b.provider && (
          <p className="subtle billing__hint">
            Billing isn't configured on this server, so the plan can't be changed here.
          </p>
        )}
        {note && <p className="billing__provider">{note}</p>}
      </div>

      <PlansModal open={plansOpen} onClose={() => setPlansOpen(false)} billing={b} canManage={canManage} />
    </section>
  );
}
