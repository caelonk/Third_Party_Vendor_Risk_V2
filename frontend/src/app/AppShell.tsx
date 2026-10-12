import { useState } from "react";
import {
  Bell,
  Check,
  ChevronDown,
  ChevronUp,
  ChevronsUpDown,
  FileText,
  LayoutDashboard,
  LogOut,
  PanelLeftClose,
  PanelLeftOpen,
  Settings2,
  Shield,
} from "lucide-react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { Avatar } from "@/components/Avatar";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { Logo } from "@/components/Logo";
import { ThemeToggle } from "@/components/ThemeToggle";
import { ThemeSync } from "@/theme/ThemeSync";
import { useAuth } from "@/auth/AuthProvider";
import { useOrg } from "@/org/OrgProvider";
import { useUnreadCount } from "@/features/alerts";
import { useBilling } from "@/features/billing";
import { useNavCollapsed } from "./useNavCollapsed";
import "./app-shell.css";
import "@/routes/alerts.css";

function OrgSwitcher() {
  const { orgs, currentOrg, setCurrentOrgId } = useOrg();
  const [open, setOpen] = useState(false);
  if (!currentOrg) return null;
  return (
    <div className="orgswitch">
      <button
        className="orgswitch__btn"
        onClick={() => setOpen((o) => !o)}
        type="button"
        title={`Organization: ${currentOrg.name}`}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <Shield size={16} style={{ color: "var(--text-subtle)" }} />
        <span className="orgswitch__name">{currentOrg.name}</span>
        <ChevronsUpDown className="orgswitch__caret" size={15} style={{ color: "var(--text-subtle)" }} />
      </button>
      {open && (
        <>
          <div
            style={{ position: "fixed", inset: 0, zIndex: 10 }}
            onClick={() => setOpen(false)}
          />
          <div className="orgswitch__menu" role="menu">
            {orgs.map((o) => (
              <button
                key={o.id}
                className="orgswitch__item"
                type="button"
                role="menuitem"
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

const navClass = ({ isActive }: { isActive: boolean }) =>
  `navlink${isActive ? " navlink--active" : ""}`;

function AlertsNav() {
  const { data } = useUnreadCount();
  const unread = data?.unread ?? 0;
  return (
    <NavLink to="/alerts" title="Alerts" className={navClass}>
      <Bell />
      <span className="navlink__label">Alerts</span>
      {unread > 0 && (
        <span className="navbadge" aria-label={`${unread} unread`}>
          {unread > 99 ? "99+" : unread}
        </span>
      )}
    </NavLink>
  );
}

export function AppShell() {
  const { user, logout } = useAuth();
  const { collapsed, mobile, toggle } = useNavCollapsed();
  const { pathname } = useLocation();
  // The same control collapses the sidebar on a wide screen and the header on a
  // narrow one; only its wording and icon differ.
  const region = mobile ? "menu" : "sidebar";
  const ToggleIcon = mobile
    ? collapsed
      ? ChevronDown
      : ChevronUp
    : collapsed
      ? PanelLeftOpen
      : PanelLeftClose;
  const toggleLabel = `${collapsed ? "Expand" : "Collapse"} ${region}`;

  return (
    <div className="shell" data-nav={collapsed ? "collapsed" : "expanded"}>
      <ThemeSync />
      <aside className="sidebar">
        <div className="sidebar__brand">
          <NavLink to="/" className="sidebar__logo" title="VendorRisk">
            <Logo size={24} />
            <span className="sidebar__wordmark">
              Vendor<span>Risk</span>
            </span>
          </NavLink>
          <button
            type="button"
            className="icon-btn sidebar__toggle"
            onClick={toggle}
            aria-expanded={!collapsed}
            aria-controls="sidebar-more"
            aria-label={toggleLabel}
            title={toggleLabel}
          >
            <ToggleIcon />
          </button>
        </div>

        <nav className="sidebar__nav" aria-label="Main">
          <NavLink to="/" end title="Dashboard" className={navClass}>
            <LayoutDashboard />
            <span className="navlink__label">Dashboard</span>
          </NavLink>
          <NavLink to="/vendors" title="Vendors" className={navClass}>
            <Shield />
            <span className="navlink__label">Vendors</span>
          </NavLink>
          <AlertsNav />
          <NavLink to="/reports" title="Reports" className={navClass}>
            <FileText />
            <span className="navlink__label">Reports</span>
          </NavLink>
          <NavLink to="/settings" title="Settings" className={navClass}>
            <Settings2 />
            <span className="navlink__label">Settings</span>
          </NavLink>
        </nav>

        <div className="sidebar__spacer" />

        <div className="sidebar__foot" id="sidebar-more">
          <OrgSwitcher />
          <ThemeToggle />
          {user && (
            <div className="userbar">
              <NavLink
                to="/profile"
                title="Your profile"
                className={({ isActive }) =>
                  `userbar__link${isActive ? " userbar__link--active" : ""}`
                }
              >
                <Avatar user={user} />
                <span className="userbar__meta">
                  <span className="userbar__name">{user.name ?? "You"}</span>
                  <span className="userbar__email">{user.email}</span>
                </span>
              </NavLink>
              <button
                type="button"
                className="icon-btn"
                title="Sign out"
                aria-label="Sign out"
                onClick={() => void logout()}
              >
                <LogOut />
              </button>
            </div>
          )}
        </div>
      </aside>

      <div className="main">
        <div className="main__inner">
          <PastDueBanner />
          <ErrorBoundary key={pathname}>
            <Outlet />
          </ErrorBoundary>
        </div>
      </div>
    </div>
  );
}

/** Owners see a failed renewal payment everywhere, not only in Settings. */
function PastDueBanner() {
  const { currentOrg } = useOrg();
  const isOwner = currentOrg?.role === "owner";
  const billing = useBilling({ enabled: isOwner });
  const b = billing.data;
  if (!isOwner || !b || b.status !== "past_due" || !b.has_subscription) return null;
  return (
    <div className="banner banner--error shell__alert" role="alert">
      <span>
        The last payment for the {b.plan.name} plan failed.{" "}
        <Link className="banner__link" to="/settings#billing">
          Update billing
        </Link>
      </span>
    </div>
  );
}
