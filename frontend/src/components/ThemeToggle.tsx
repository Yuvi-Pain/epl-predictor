import { useEffect, useState } from "react";
import { Monitor, Moon, Sun } from "./Icons";

type Theme = "system" | "light" | "dark";
const STORAGE_KEY = "theme";

const OPTIONS = [
  { value: "system", label: "Match system theme", Icon: Monitor },
  { value: "light", label: "Light theme", Icon: Sun },
  { value: "dark", label: "Dark theme", Icon: Moon },
] as const;

function readTheme(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    // Storage blocked (private mode): fall back to the system theme.
  }
  return "system";
}

/** System / light / dark. "System" follows prefers-color-scheme via CSS. */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(readTheme);

  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    try {
      if (theme === "system") localStorage.removeItem(STORAGE_KEY);
      else localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      // Not remembered, but still applied for this visit.
    }
  }, [theme]);

  return (
    <div className="theme-toggle" role="group" aria-label="Colour theme">
      {OPTIONS.map(({ value, label, Icon }) => (
        <button
          key={value}
          type="button"
          aria-pressed={theme === value}
          aria-label={label}
          title={label}
          onClick={() => setTheme(value)}
        >
          <Icon />
        </button>
      ))}
    </div>
  );
}
