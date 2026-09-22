import { useEffect, useRef } from "react";
import { usePreferences, useUpdatePreferences } from "@/features/preferences";
import { useTheme } from "./ThemeProvider";

/** Reconciles the theme with the server: adopt the stored preference once on
 * load (cross-device source of truth), then push later user changes back. */
export function ThemeSync() {
  const { theme, setTheme } = useTheme();
  const { data: prefs } = usePreferences();
  const update = useUpdatePreferences();
  const adopted = useRef(false);
  const lastSynced = useRef<string | null>(null);

  useEffect(() => {
    if (!prefs || adopted.current) return;
    adopted.current = true;
    lastSynced.current = prefs.theme;
    if (prefs.theme !== theme) setTheme(prefs.theme);
  }, [prefs, theme, setTheme]);

  useEffect(() => {
    if (!adopted.current || lastSynced.current === theme) return;
    lastSynced.current = theme;
    update.mutate({ theme });
  }, [theme, update]);

  return null;
}
