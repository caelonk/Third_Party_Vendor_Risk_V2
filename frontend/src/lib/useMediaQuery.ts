import { useEffect, useState } from "react";

/** Below this width the sidebar becomes a header and the dashboard a single column. */
export const NARROW_SCREEN = "(max-width: 780px)";

/** Whether a CSS media query currently matches; re-renders when that changes. */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const onChange = () => setMatches(mq.matches);
    onChange();
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [query]);
  return matches;
}
