import { useCallback, useEffect, useState } from "react";

/** Matches the breakpoint in app-shell.css where the sidebar becomes a header. */
const MOBILE_QUERY = "(max-width: 780px)";
// Remembered separately: the sidebar (wide screens) and the header (narrow ones).
const KEYS = { desktop: "vr-sidebar-collapsed", mobile: "vr-header-collapsed" } as const;
// A wide screen has room for the full sidebar; a narrow one starts compact.
const DEFAULTS = { desktop: false, mobile: true } as const;

function read(key: string, fallback: boolean): boolean {
  try {
    const raw = localStorage.getItem(key);
    return raw === null ? fallback : raw === "1";
  } catch {
    return fallback; // storage blocked (private mode): still usable, just not remembered
  }
}

function useIsMobile(): boolean {
  const [mobile, setMobile] = useState(() => window.matchMedia(MOBILE_QUERY).matches);
  useEffect(() => {
    const mq = window.matchMedia(MOBILE_QUERY);
    const onChange = () => setMobile(mq.matches);
    onChange();
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return mobile;
}

/** Whether the navigation is collapsed, and a toggle that remembers the choice. */
export function useNavCollapsed() {
  const mobile = useIsMobile();
  const [state, setState] = useState(() => ({
    desktop: read(KEYS.desktop, DEFAULTS.desktop),
    mobile: read(KEYS.mobile, DEFAULTS.mobile),
  }));
  const mode = mobile ? "mobile" : "desktop";

  const toggle = useCallback(() => {
    setState((prev) => {
      const next = { ...prev, [mode]: !prev[mode] };
      try {
        localStorage.setItem(KEYS[mode], next[mode] ? "1" : "0");
      } catch {
        /* not remembered; see read() */
      }
      return next;
    });
  }, [mode]);

  return { collapsed: state[mode], mobile, toggle };
}
