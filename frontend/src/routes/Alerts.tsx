import { useState } from "react";
import { BellRing, CalendarClock, Flame, TrendingUp } from "lucide-react";
import { fmtRelative } from "@/lib/format";
import { useOrg } from "@/org/OrgProvider";
import {
  useAlertRules,
  useCreateRule,
  useMarkAllRead,
  useMarkRead,
  useNotifications,
  useUpdateRule,
} from "@/features/alerts";
import type { AlertRule, AlertType } from "@/lib/types";
import "./alerts.css";

const RULE_META: { type: AlertType; title: string; desc: string; icon: typeof Flame }[] = [
  {
    type: "new_kev",
    title: "New known-exploited CVE",
    desc: "When a vendor gains a CISA KEV-listed vulnerability after a sync.",
    icon: Flame,
  },
  {
    type: "tier_change",
    title: "Risk tier change",
    desc: "When a vendor's risk tier changes between syncs.",
    icon: TrendingUp,
  },
  {
    type: "renewal_due",
    title: "Renewal due",
    desc: "When a High/Critical vendor's contract renews within the window.",
    icon: CalendarClock,
  },
];

function Switch({
  checked,
  disabled,
  onChange,
}: {
  checked: boolean;
  disabled?: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      className="switch"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
    />
  );
}

export function Alerts() {
  const { currentOrg } = useOrg();
  const canManage = currentOrg ? ["owner", "admin"].includes(currentOrg.role) : false;

  const rules = useAlertRules();
  const create = useCreateRule();
  const update = useUpdateRule();

  const notifications = useNotifications();
  const markRead = useMarkRead();
  const markAll = useMarkAllRead();

  const byType = (t: AlertType): AlertRule | undefined => rules.data?.find((r) => r.type === t);
  const [renewalDays, setRenewalDays] = useState(90);

  const toggle = (t: AlertType, on: boolean) => {
    const existing = byType(t);
    if (existing) {
      update.mutate({ id: existing.id, is_active: on });
    } else if (on) {
      create.mutate({
        type: t,
        channel: "email",
        config: t === "renewal_due" ? { days: renewalDays } : {},
      });
    }
  };

  const items = notifications.data ?? [];
  const unread = items.filter((n) => !n.read_at).length;

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Alerts</h1>
          <p>Get notified when a vendor's risk changes. Notifications appear here in-app.</p>
        </div>
        {unread > 0 && (
          <button className="btn btn--secondary" onClick={() => markAll.mutate()}>
            Mark all read
          </button>
        )}
      </div>

      <div className="alerts">
        <section className="card">
          <div className="card__header">
            <span className="card__title">Alert rules</span>
          </div>
          <div className="card__body" style={{ paddingTop: 0, paddingBottom: 0 }}>
            {RULE_META.map((m) => {
              const rule = byType(m.type);
              const active = !!rule?.is_active;
              return (
                <div className="rule" key={m.type}>
                  <m.icon size={18} className="rule__icon" />
                  <div className="rule__meta">
                    <div className="rule__title">{m.title}</div>
                    <div className="rule__desc">{m.desc}</div>
                    {m.type === "renewal_due" && active && (
                      <div className="rule__config">
                        Window
                        <input
                          className="input mono"
                          type="number"
                          min={1}
                          max={365}
                          value={Number(rule?.config?.days ?? renewalDays)}
                          disabled={!canManage}
                          onChange={(e) => {
                            const days = Number(e.target.value) || 90;
                            setRenewalDays(days);
                            if (rule) update.mutate({ id: rule.id, config: { days } });
                          }}
                        />
                        days
                      </div>
                    )}
                  </div>
                  <Switch
                    checked={active}
                    disabled={!canManage}
                    onChange={(v) => toggle(m.type, v)}
                  />
                </div>
              );
            })}
          </div>
        </section>

        <section className="card">
          <div className="card__header">
            <span className="card__title">Notifications</span>
            {unread > 0 && <span className="pill">{unread} unread</span>}
          </div>
          <div className="card__body">
            {items.length === 0 ? (
              <div className="empty">
                <BellRing />
                <p className="subtle">No notifications yet. Enable a rule and sync your vendors.</p>
              </div>
            ) : (
              <div className="feed">
                {items.map((n) => (
                  <div
                    key={n.id}
                    className={`notif${n.read_at ? " notif--read" : ""}`}
                    onClick={() => !n.read_at && markRead.mutate(n.id)}
                  >
                    <span className="notif__dot" />
                    <div className="notif__body">
                      <div className="notif__title">{n.title}</div>
                      {n.body && <div className="notif__sub">{n.body}</div>}
                    </div>
                    <span className="notif__time">{fmtRelative(n.created_at)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>
      </div>

      {!canManage && (
        <p className="subtle" style={{ fontSize: "0.78rem", marginTop: "var(--space-4)" }}>
          Only admins and owners can change alert rules.
        </p>
      )}
    </>
  );
}
