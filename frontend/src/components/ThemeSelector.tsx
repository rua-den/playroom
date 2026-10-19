import { useEffect, useState } from "react";

export type ThemeChoice = "system" | "light" | "dark";
const STORAGE_KEY = "playroom:theme";

function readTheme(): ThemeChoice {
  const value = localStorage.getItem(STORAGE_KEY);
  return value === "light" || value === "dark" ? value : "system";
}

function applyTheme(theme: ThemeChoice) {
  if (theme === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.dataset.theme = theme;
}

export function applyStoredTheme() { applyTheme(readTheme()); }
applyStoredTheme();

export function ThemeSelector() {
  const [theme, setTheme] = useState<ThemeChoice>(() => readTheme());
  useEffect(() => { applyTheme(theme); localStorage.setItem(STORAGE_KEY, theme); }, [theme]);
  return <label className="theme-selector" htmlFor="theme-choice"><span>Giao diện</span><select id="theme-choice" className="touch-target" value={theme} onChange={(event) => setTheme(event.target.value as ThemeChoice)}><option value="system">Theo thiết bị</option><option value="light">Sáng</option><option value="dark">Tối</option></select></label>;
}
