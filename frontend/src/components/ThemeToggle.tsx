import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "@/theme/ThemeProvider";
import type { Theme } from "@/lib/types";
import "./theme-toggle.css";

const OPTIONS: { value: Theme; icon: typeof Sun; label: string }[] = [
  { value: "light", icon: Sun, label: "Light" },
  { value: "dark", icon: Moon, label: "Dark" },
  { value: "system", icon: Monitor, label: "System" },
];

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  return (
    <div className="seg" role="group" aria-label="Theme">
      {OPTIONS.map(({ value, icon: Icon, label }) => (
        <button
          key={value}
          type="button"
          className={`seg__btn${theme === value ? " seg__btn--on" : ""}`}
          aria-pressed={theme === value}
          title={label}
          onClick={() => setTheme(value)}
        >
          <Icon />
        </button>
      ))}
    </div>
  );
}
