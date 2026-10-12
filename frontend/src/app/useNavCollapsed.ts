import { useCallback, useState } from "react";
import { NARROW_SCREEN, useMediaQuery } from "@/lib/useMediaQuery";

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

/** Whether the navigation is collapsed, and a toggle that remembers the choice. */
export function useNavCollapsed() {
  // Matches the breakpoint in app-shell.css where the sidebar becomes a header.
  const mobile = useMediaQuery(NARROW_SCREEN);
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
