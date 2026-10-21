import { useSyncExternalStore } from "react";

export type ThemeChoice = "system" | "light" | "dark";
const STORAGE_KEY = "playroom:theme";

function readTheme(): ThemeChoice {
  let value: string | null = null;
  try { value = localStorage.getItem(STORAGE_KEY); } catch { /* Keep the device default when storage is blocked. */ }
  return value === "light" || value === "dark" ? value : "system";
}

let theme = readTheme();
const listeners = new Set<() => void>();
const deviceTheme = () => window.matchMedia?.("(prefers-color-scheme: dark)");
const isDark = () => theme === "dark" || (theme === "system" && (deviceTheme()?.matches ?? true));

function applyTheme() {
  if (theme === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.dataset.theme = theme;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", isDark() ? "#201d19" : "#f5f0e7");
}

function notify() { applyTheme(); listeners.forEach((listener) => listener()); }
function setTheme(next: ThemeChoice) {
  theme = next;
  try { localStorage.setItem(STORAGE_KEY, next); } catch { /* The choice still works for this session. */ }
  notify();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  const media = deviceTheme();
  const onDeviceChange = () => { applyTheme(); listener(); };
  const onStorage = (event: StorageEvent) => { if (event.key === STORAGE_KEY || event.key === null) applyStoredTheme(); };
  media?.addEventListener("change", onDeviceChange);
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    media?.removeEventListener("change", onDeviceChange);
    window.removeEventListener("storage", onStorage);
  };
}

export function applyStoredTheme() { theme = readTheme(); notify(); }
applyStoredTheme();

export function ThemeSelector() {
  const choice = useSyncExternalStore(subscribe, () => theme);
  return <label className="theme-selector" htmlFor="theme-choice"><span>Giao diện</span><select id="theme-choice" className="touch-target" value={choice} onChange={(event) => setTheme(event.target.value as ThemeChoice)}><option value="system">Theo thiết bị</option><option value="light">Sáng</option><option value="dark">Tối</option></select></label>;
}

export function ThemeToggle() {
  const dark = useSyncExternalStore(subscribe, isDark);
  return <button type="button" className="quiet-button touch-target theme-toggle" aria-label={dark ? "Chuyển sang giao diện sáng" : "Chuyển sang giao diện tối"} onClick={() => setTheme(dark ? "light" : "dark")}>{dark ? "Sáng" : "Tối"}</button>;
}
