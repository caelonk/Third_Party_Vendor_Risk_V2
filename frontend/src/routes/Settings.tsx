import { useState } from "react";
import { Copy, UserPlus } from "lucide-react";
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
import type { Role } from "@/lib/types";
import "./settings.css";

const ROLES: Role[] = ["owner", "admin", "member", "viewer"];

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
          <p>Manage your appearance, organization, and team.</p>
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
