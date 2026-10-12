import { type FormEvent, useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { Clock, Copy, KeyRound, UserPlus } from "lucide-react";
import { Avatar } from "@/components/Avatar";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Modal } from "@/components/Modal";
import { ThemeToggle } from "@/components/ThemeToggle";
import { fmtDate } from "@/lib/format";
import { useAuth } from "@/auth/AuthProvider";
import { useOrg } from "@/org/OrgProvider";
import {
  useCreateInvitation,
  useInvitations,
  useMembers,
  useRemoveMember,
  useSetMemberRole,
  useUpdateMemberDetails,
} from "@/features/members";
import { useIntegration, useUpdateIntegration } from "@/features/integration";
import { BillingCard } from "./BillingCard";
import type { Member, Role } from "@/lib/types";
import "./settings.css";

const ROLES: Role[] = ["owner", "admin", "member", "viewer"];

function AutoSyncCard({ canManage }: { canManage: boolean }) {
  const integration = useIntegration();
  const update = useUpdateIntegration();
  const [cadence, setCadence] = useState(24);
  const [keyInput, setKeyInput] = useState("");
  const [status, setStatus] = useState<{ ok: true; msg: string } | { ok: false; error: unknown } | null>(null);

  const loadedCadence = integration.data?.sync_cadence_hours;
  useEffect(() => {
    if (loadedCadence !== undefined) setCadence(loadedCadence);
  }, [loadedCadence]);

  const keySet = integration.data?.nvd_key_set ?? false;
  const verifiedAt = integration.data?.nvd_key_verified_at ?? null;
  const minHours = integration.data?.min_sync_hours ?? 1;
  const clamp = (n: number) => Math.max(1, Math.min(720, n || 1));

  const save = () => {
    setStatus(null);
    const payload: { sync_cadence_hours: number; nvd_api_key?: string } = {
      sync_cadence_hours: cadence,
    };
    const savingKey = !!keyInput.trim();
    if (savingKey) payload.nvd_api_key = keyInput.trim();
    update.mutate(payload, {
      onSuccess: (saved) => {
        setKeyInput("");
        setStatus({
          ok: true,
          msg: !savingKey
            ? "Sync settings saved."
            : saved.nvd_key_verified_at
              ? "Saved. NVD accepted the API key."
              : "Saved, but NVD could not be reached to confirm the key.",
        });
      },
      onError: (e) => setStatus({ ok: false, error: e }),
    });
  };

  const removeKey = () => {
    setStatus(null);
    update.mutate(
      { nvd_api_key: "" },
      {
        onSuccess: () => setStatus({ ok: true, msg: "API key removed." }),
        onError: (e) => setStatus({ ok: false, error: e }),
      },
    );
  };

  return (
    <section className="card">
      <div className="card__header">
        <span className="card__title">Automated sync</span>
      </div>
      <div className="card__body">
        <p className="subtle" style={{ marginTop: 0, fontSize: "0.85rem" }}>
          Mapped vendors are re-checked against the NVD feed on a schedule, so risk scores and KEV
          status stay current without manual syncs.
        </p>

        {status?.ok && (
          <div className="banner banner--ok" style={{ margin: "var(--space-3) 0" }}>
            {status.msg}
          </div>
        )}
        {status && !status.ok && (
          <ErrorBanner error={status.error} fallback="Could not save" style={{ margin: "var(--space-3) 0" }} />
        )}

        <div className="settings__field">
          <label className="settings__label">
            <Clock size={15} /> Check frequency
          </label>
          <div className="settings__inline">
            <span className="subtle">Every</span>
            <input
              className="input mono"
              type="number"
              min={1}
              max={720}
              style={{ width: 92 }}
              value={cadence}
              disabled={!canManage}
              onChange={(e) => setCadence(clamp(Number(e.target.value)))}
            />
            <span className="subtle">hours</span>
          </div>
          {minHours > 1 && (
            <p className="subtle settings__plan-note">
              {cadence < minHours
                ? `Your plan syncs at most every ${minHours} hours, so this runs every ${minHours} hours.`
                : `Your plan allows syncing as often as every ${minHours} hours.`}
            </p>
          )}
        </div>

        <div className="settings__field">
          <label className="settings__label">
            <KeyRound size={15} /> NVD API key
          </label>
          <p className="subtle" style={{ fontSize: "0.8rem", margin: "0 0 var(--space-2)" }}>
            {!keySet
              ? "No key set, so syncs use the shared limit of 5 requests per 30 seconds. Your own key raises that to 50."
              : verifiedAt
                ? `A key is set for this organization. NVD accepted it on ${fmtDate(verifiedAt)}.`
                : "A key is saved, but NVD could not be reached to confirm it. Syncs will use it; save it again to re-check."}
          </p>
          {canManage && (
            <div className="settings__inline">
              <input
                className="input mono"
                type="password"
                autoComplete="off"
                placeholder={keySet ? "Enter a new key to replace it" : "Paste your NVD API key"}
                value={keyInput}
                onChange={(e) => setKeyInput(e.target.value)}
                style={{ flex: 1, minWidth: 200 }}
              />
              {keySet && (
                <button
                  className="btn btn--ghost btn--sm"
                  onClick={removeKey}
                  disabled={update.isPending}
                >
                  Remove
                </button>
              )}
            </div>
          )}
        </div>

        {canManage ? (
          <button
            className="btn btn--primary"
            style={{ marginTop: "var(--space-2)" }}
            disabled={update.isPending}
            onClick={save}
          >
            {update.isPending && keyInput.trim() ? "Checking the key with NVD…" : "Save"}
          </button>
        ) : (
          <p className="subtle" style={{ fontSize: "0.78rem", marginTop: "var(--space-2)" }}>
            Only admins and owners can change sync settings.
          </p>
        )}
      </div>
    </section>
  );
}

/** Admins record a member's employee ID and team; the member sees them on their profile. */
function MemberDetailsModal({ member, onClose }: { member: Member | null; onClose: () => void }) {
  const update = useUpdateMemberDetails();
  const [employeeId, setEmployeeId] = useState("");
  const [team, setTeam] = useState("");
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!member) return;
    setEmployeeId(member.employee_id ?? "");
    setTeam(member.team ?? "");
    setError(null);
  }, [member]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!member) return;
    setError(null);
    update.mutate(
      { userId: member.user_id, employee_id: employeeId, team },
      { onSuccess: onClose, onError: setError },
    );
  };

  return (
    <Modal open={!!member} onClose={onClose} title="Member details">
      <form className="settings__member-form" onSubmit={submit} noValidate>
        <p className="subtle" style={{ margin: 0, fontSize: "var(--text-sm)" }}>
          {member?.name ?? member?.email} sees these on their profile. Both are optional; leave
          one blank to clear it.
        </p>
        <ErrorBanner error={error} fallback="Could not save" />
        <div className="field">
          <label className="field__label" htmlFor="member-employee-id">
            Employee ID
          </label>
          <input
            id="member-employee-id"
            className="input mono"
            maxLength={64}
            autoComplete="off"
            value={employeeId}
            onChange={(e) => setEmployeeId(e.target.value)}
          />
          <span className="field__hint">Unique within this organization.</span>
        </div>
        <div className="field">
          <label className="field__label" htmlFor="member-team">
            Team
          </label>
          <input
            id="member-team"
            className="input"
            maxLength={100}
            autoComplete="off"
            value={team}
            onChange={(e) => setTeam(e.target.value)}
          />
        </div>
        <div className="settings__modal-actions">
          <button type="button" className="btn btn--ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn--primary" disabled={update.isPending}>
            {update.isPending ? <span className="spinner" /> : "Save"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function Settings() {
  const { user } = useAuth();
  const { currentOrg } = useOrg();
  const canManage = currentOrg ? ["owner", "admin"].includes(currentOrg.role) : false;
  const { hash } = useLocation();

  // Deep links such as /settings#billing (the "See plans" link) land on the card.
  // The target card may render only once its data loads, so retry briefly.
  useEffect(() => {
    if (!hash) return;
    let tries = 0;
    const t = setInterval(() => {
      const el = document.getElementById(hash.slice(1));
      if (el || ++tries > 20) {
        el?.scrollIntoView({ block: "start" });
        clearInterval(t);
      }
    }, 100);
    return () => clearInterval(t);
  }, [hash]);

  const members = useMembers();
  const invitations = useInvitations(canManage);
  const invite = useCreateInvitation();
  const setRole = useSetMemberRole();
  const removeMember = useRemoveMember();

  const [editing, setEditing] = useState<Member | null>(null);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<Role>("member");
  const [inviteError, setInviteError] = useState<unknown>(null);

  const sendInvite = () => {
    setInviteError(null);
    invite.mutate(
      { email: inviteEmail, role: inviteRole },
      {
        onSuccess: () => setInviteEmail(""),
        onError: (e) => setInviteError(e),
      },
    );
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Settings</h1>
          <p>
            Manage your appearance, organization, and team. Your name, photo and password are
            on <Link to="/profile">your profile</Link>.
          </p>
        </div>
      </div>

      <div className="settings">
        <section className="card">
          <div className="card__header">
            <span className="card__title">Appearance</span>
          </div>
          <div className="card__body spread">
            <div>
              <div style={{ fontWeight: 500 }}>Theme</div>
              <p className="subtle" style={{ fontSize: "0.82rem", marginTop: 2 }}>
                Saved to your account and this device.
              </p>
            </div>
            <ThemeToggle />
          </div>
        </section>

        <section className="card">
          <div className="card__header">
            <span className="card__title">Organization</span>
          </div>
          <div className="card__body">
            <dl className="kv">
              <dt>Name</dt>
              <dd>{currentOrg?.name}</dd>
              <dt>Your role</dt>
              <dd style={{ textTransform: "capitalize" }}>{currentOrg?.role}</dd>
            </dl>
          </div>
        </section>

        <BillingCard canManage={currentOrg?.role === "owner"} />

        <AutoSyncCard canManage={canManage} />

        <section className="card" id="members">
          <div className="card__header">
            <span className="card__title">Members</span>
          </div>
          <div className="card__body settings__members">
            <table className="table">
              <thead>
                <tr>
                  <th>Member</th>
                  <th>Role</th>
                  {canManage && <th />}
                </tr>
              </thead>
              <tbody>
                {members.data?.map((m) => {
                  const isSelf = m.user_id === user?.id;
                  const details = [m.employee_id && `ID ${m.employee_id}`, m.team]
                    .filter(Boolean)
                    .join(" · ");
                  return (
                    <tr key={m.user_id}>
                      <td>
                        <div className="settings__member">
                          <Avatar user={m} size={30} />
                          <div className="settings__member-main">
                            <div style={{ fontWeight: 500 }}>
                              {m.name ?? m.email} {isSelf && <span className="subtle">(you)</span>}
                            </div>
                            <div className="subtle settings__member-meta">{m.email}</div>
                            {details && <div className="subtle settings__member-meta">{details}</div>}
                          </div>
                        </div>
                      </td>
                      <td>
                        {canManage && !isSelf ? (
                          <select
                            className="select"
                            style={{ height: 32, maxWidth: 140 }}
                            value={m.role}
                            onChange={(e) =>
                              setRole.mutate({ userId: m.user_id, role: e.target.value as Role })
                            }
                          >
                            {ROLES.map((r) => (
                              <option key={r} value={r}>
                                {r}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <span style={{ textTransform: "capitalize" }}>{m.role}</span>
                        )}
                      </td>
                      {canManage && (
                        <td>
                          <div className="settings__member-actions">
                            <button
                              className="btn btn--ghost btn--sm"
                              onClick={() => setEditing(m)}
                            >
                              Edit
                            </button>
                            {!isSelf && (
                              <button
                                className="btn btn--ghost btn--sm"
                                onClick={() => removeMember.mutate(m.user_id)}
                              >
                                Remove
                              </button>
                            )}
                          </div>
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>

        <MemberDetailsModal member={editing} onClose={() => setEditing(null)} />

        {canManage && (
          <section className="card">
            <div className="card__header">
              <span className="card__title">Invite a teammate</span>
            </div>
            <div className="card__body">
              <ErrorBanner error={inviteError} fallback="Could not invite" style={{ marginBottom: "var(--space-4)" }} />
              <div className="settings__invite">
                <input
                  className="input"
                  type="email"
                  placeholder="teammate@company.com"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                />
                <select
                  className="select"
                  value={inviteRole}
                  onChange={(e) => setInviteRole(e.target.value as Role)}
                >
                  {ROLES.filter((r) => r !== "owner").map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
                <button
                  className="btn btn--primary"
                  disabled={invite.isPending || !inviteEmail}
                  onClick={sendInvite}
                >
                  <UserPlus /> Invite
                </button>
              </div>

              {invitations.data && invitations.data.length > 0 && (
                <div className="settings__invites">
                  <div className="eyebrow" style={{ marginBottom: "var(--space-2)" }}>
                    Pending invitations
                  </div>
                  {invitations.data.map((inv) => (
                    <div key={inv.id} className="settings__invite-row">
                      <span>{inv.email}</span>
                      <span className="pill">{inv.role}</span>
                      <span className="subtle" style={{ fontSize: "0.75rem" }}>
                        expires {fmtDate(inv.expires_at)}
                      </span>
                      <button
                        className="icon-btn"
                        title="Copy invite token"
                        onClick={() => navigator.clipboard?.writeText(inv.token)}
                      >
                        <Copy />
                      </button>
                    </div>
                  ))}
                  <p className="subtle" style={{ fontSize: "0.75rem", marginTop: "var(--space-2)" }}>
                    Share the token with the invitee — they accept it after signing in. (Email
                    delivery arrives in a later phase.)
                  </p>
                </div>
              )}
            </div>
          </section>
        )}
      </div>
    </>
  );
}
