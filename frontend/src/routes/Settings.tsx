import { useEffect, useState } from "react";
import { Clock, Copy, KeyRound, UserPlus } from "lucide-react";
import { ThemeToggle } from "@/components/ThemeToggle";
import { ApiError } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { useAuth } from "@/auth/AuthProvider";
import { useOrg } from "@/org/OrgProvider";
import {
  useCreateInvitation,
  useInvitations,
  useMembers,
  useRemoveMember,
  useSetMemberRole,
} from "@/features/members";
import { useIntegration, useUpdateIntegration } from "@/features/integration";
import { SecurityCard } from "./SecurityCard";
import type { Role } from "@/lib/types";
import "./settings.css";

const ROLES: Role[] = ["owner", "admin", "member", "viewer"];

function AutoSyncCard({ canManage }: { canManage: boolean }) {
  const integration = useIntegration();
  const update = useUpdateIntegration();
  const [cadence, setCadence] = useState(24);
  const [keyInput, setKeyInput] = useState("");
  const [status, setStatus] = useState<{ ok: boolean; msg: string } | null>(null);

  const loadedCadence = integration.data?.sync_cadence_hours;
  useEffect(() => {
    if (loadedCadence !== undefined) setCadence(loadedCadence);
  }, [loadedCadence]);

  const keySet = integration.data?.nvd_key_set ?? false;
  const clamp = (n: number) => Math.max(1, Math.min(720, n || 1));

  const save = () => {
    setStatus(null);
    const payload: { sync_cadence_hours: number; nvd_api_key?: string } = {
      sync_cadence_hours: cadence,
    };
    if (keyInput.trim()) payload.nvd_api_key = keyInput.trim();
    update.mutate(payload, {
      onSuccess: () => {
        setKeyInput("");
        setStatus({ ok: true, msg: "Sync settings saved." });
      },
      onError: (e) =>
        setStatus({ ok: false, msg: e instanceof ApiError ? e.message : "Could not save" }),
    });
  };

  const removeKey = () => {
    setStatus(null);
    update.mutate(
      { nvd_api_key: "" },
      {
        onSuccess: () => setStatus({ ok: true, msg: "API key removed." }),
        onError: (e) =>
          setStatus({ ok: false, msg: e instanceof ApiError ? e.message : "Could not remove key" }),
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

        {status && (
          <div
            className={`banner ${status.ok ? "banner--ok" : "banner--error"}`}
            style={{ margin: "var(--space-3) 0" }}
          >
            {status.msg}
          </div>
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
        </div>

        <div className="settings__field">
          <label className="settings__label">
            <KeyRound size={15} /> NVD API key
          </label>
          <p className="subtle" style={{ fontSize: "0.8rem", margin: "0 0 var(--space-2)" }}>
            {keySet
              ? "A key is configured for this organization — higher NVD rate limit."
              : "No key set — using the shared system key. Add your own for faster syncs."}
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
            Save
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

export function Settings() {
  const { user } = useAuth();
  const { currentOrg } = useOrg();
  const canManage = currentOrg ? ["owner", "admin"].includes(currentOrg.role) : false;

  const members = useMembers();
  const invitations = useInvitations(canManage);
  const invite = useCreateInvitation();
  const setRole = useSetMemberRole();
  const removeMember = useRemoveMember();

  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<Role>("member");
  const [inviteError, setInviteError] = useState<string | null>(null);

  const sendInvite = () => {
    setInviteError(null);
    invite.mutate(
      { email: inviteEmail, role: inviteRole },
      {
        onSuccess: () => setInviteEmail(""),
        onError: (e) => setInviteError(e instanceof ApiError ? e.message : "Could not invite"),
      },
    );
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Settings</h1>
          <p>Manage your appearance, sign-in, organization, and team.</p>
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

        <SecurityCard />

        <section className="card">
          <div className="card__header">
            <span className="card__title">Organization</span>
          </div>
          <div className="card__body">
            <div className="settings__kv">
              <span className="subtle">Name</span>
              <span>{currentOrg?.name}</span>
              <span className="subtle">Plan</span>
              <span style={{ textTransform: "capitalize" }}>{currentOrg?.plan}</span>
              <span className="subtle">Your role</span>
              <span style={{ textTransform: "capitalize" }}>{currentOrg?.role}</span>
            </div>
          </div>
        </section>

        <AutoSyncCard canManage={canManage} />

        <section className="card">
          <div className="card__header">
            <span className="card__title">Members</span>
          </div>
          <div className="card__body" style={{ padding: 0 }}>
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
                  return (
                    <tr key={m.user_id}>
                      <td>
                        <div style={{ fontWeight: 500 }}>
                          {m.name ?? m.email} {isSelf && <span className="subtle">(you)</span>}
                        </div>
                        <div className="subtle" style={{ fontSize: "0.75rem" }}>
                          {m.email}
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
                        <td className="num">
                          {!isSelf && (
                            <button
                              className="btn btn--ghost btn--sm"
                              onClick={() => removeMember.mutate(m.user_id)}
                            >
                              Remove
                            </button>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>

        {canManage && (
          <section className="card">
            <div className="card__header">
              <span className="card__title">Invite a teammate</span>
            </div>
            <div className="card__body">
              {inviteError && (
                <div className="banner banner--error" style={{ marginBottom: "var(--space-4)" }}>
                  {inviteError}
                </div>
              )}
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
