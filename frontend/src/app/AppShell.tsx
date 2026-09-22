import { useState } from "react";
import { Check, ChevronsUpDown, LayoutDashboard, LogOut, Settings2, Shield } from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";
import { Logo } from "@/components/Logo";
import { ThemeToggle } from "@/components/ThemeToggle";
import { ThemeSync } from "@/theme/ThemeSync";
import { useAuth } from "@/auth/AuthProvider";
import { useOrg } from "@/org/OrgProvider";
import "./app-shell.css";

function initials(name: string | null, email: string) {
  if (name) {
    const parts = name.trim().split(/\s+/);
    return (parts[0][0] + (parts[1]?.[0] ?? "")).toUpperCase();
  }
  return email.slice(0, 2).toUpperCase();
}

function OrgSwitcher() {
  const { orgs, currentOrg, setCurrentOrgId } = useOrg();
  const [open, setOpen] = useState(false);
  if (!currentOrg) return null;
  return (
    <div className="orgswitch">
      <button className="orgswitch__btn" onClick={() => setOpen((o) => !o)} type="button">
        <Shield size={16} style={{ color: "var(--text-subtle)" }} />
        <span className="orgswitch__name">{currentOrg.name}</span>
        <ChevronsUpDown size={15} style={{ color: "var(--text-subtle)" }} />
      </button>
      {open && (
        <>
          <div
            style={{ position: "fixed", inset: 0, zIndex: 10 }}
            onClick={() => setOpen(false)}
          />
          <div className="orgswitch__menu">
            {orgs.map((o) => (
              <button
                key={o.id}
                className="orgswitch__item"
                type="button"
                onClick={() => {
                  setCurrentOrgId(o.id);
                  setOpen(false);
                }}
              >
                <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{o.name}</span>
                {o.id === currentOrg.id && <Check size={15} style={{ color: "var(--accent)" }} />}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

export function AppShell() {
  const { user, logout } = useAuth();

  return (
    <div className="shell">
      <ThemeSync />
      <aside className="sidebar">
        <div className="sidebar__brand">
          <NavLink to="/" style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
            <span style={{ color: "var(--text)", display: "inline-flex" }}>
              <Logo size={24} />
            </span>
            <span style={{ fontWeight: 600, color: "var(--text)", letterSpacing: "-0.01em" }}>
              Vendor<span style={{ color: "var(--text-subtle)" }}>Risk</span>
            </span>
          </NavLink>
        </div>

        <nav className="sidebar__nav">
          <NavLink
            to="/"
            end
            className={({ isActive }) => `navlink${isActive ? " navlink--active" : ""}`}
          >
            <LayoutDashboard />
            <span>Dashboard</span>
          </NavLink>
          <NavLink
            to="/vendors"
            className={({ isActive }) => `navlink${isActive ? " navlink--active" : ""}`}
          >
            <Shield />
            <span>Vendors</span>
          </NavLink>
          <NavLink
            to="/settings"
            className={({ isActive }) => `navlink${isActive ? " navlink--active" : ""}`}
          >
            <Settings2 />
            <span>Settings</span>
          </NavLink>
        </nav>

        <div className="sidebar__spacer" />

        <div className="sidebar__foot">
          <OrgSwitcher />
          <ThemeToggle />
          {user && (
            <div className="userbar">
              <div className="avatar">{initials(user.name, user.email)}</div>
              <div className="userbar__meta">
                <div className="userbar__name">{user.name ?? "You"}</div>
                <div className="userbar__email">{user.email}</div>
              </div>
              <button className="icon-btn" title="Sign out" onClick={() => void logout()}>
                <LogOut />
              </button>
            </div>
          )}
        </div>
      </aside>

      <div className="main">
        <div className="main__inner">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
