import userEvent from "@testing-library/user-event";
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeSelector, ThemeToggle, applyStoredTheme } from "./ThemeSelector";

describe("ThemeSelector", () => {
  beforeEach(() => { localStorage.clear(); applyStoredTheme(); });
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it("keeps the direct toggle and settings synchronized and restores a persisted choice", async () => {
    vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
    const user = userEvent.setup();
    const view = render(<><ThemeToggle /><ThemeSelector /></>);
    await user.click(screen.getByRole("button", { name: "Chuyển sang giao diện tối" }));
    expect(screen.getByLabelText("Giao diện")).toHaveValue("dark");
    expect(localStorage.getItem("playroom:theme")).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    await user.selectOptions(screen.getByLabelText("Giao diện"), "light");
    expect(screen.getByRole("button", { name: "Chuyển sang giao diện tối" })).toBeInTheDocument();
    view.unmount();
    applyStoredTheme();
    render(<ThemeToggle />);
    expect(document.documentElement.dataset.theme).toBe("light");
    await user.click(screen.getByRole("button", { name: "Chuyển sang giao diện tối" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("resolves system mode changes without overriding the stored preference", async () => {
    let dark = true;
    const listeners = new Set<() => void>();
    vi.stubGlobal("matchMedia", () => ({
      get matches() { return dark; },
      addEventListener: (_: string, listener: () => void) => listeners.add(listener),
      removeEventListener: (_: string, listener: () => void) => listeners.delete(listener),
    }));
    render(<><ThemeToggle /><ThemeSelector /></>);
    expect(screen.getByRole("button", { name: "Chuyển sang giao diện sáng" })).toBeInTheDocument();
    act(() => { dark = false; listeners.forEach((listener) => listener()); });
    expect(screen.getByRole("button", { name: "Chuyển sang giao diện tối" })).toBeInTheDocument();
    expect(screen.getByLabelText("Giao diện")).toHaveValue("system");
    expect(document.documentElement.dataset.theme).toBeUndefined();
  });

  it("shares changes from another tab and updates the browser theme color", () => {
    const meta = document.createElement("meta");
    meta.name = "theme-color";
    document.head.append(meta);
    render(<><ThemeToggle /><ThemeSelector /></>);
    act(() => {
      localStorage.setItem("playroom:theme", "dark");
      window.dispatchEvent(new StorageEvent("storage", { key: "playroom:theme" }));
    });
    expect(screen.getByLabelText("Giao diện")).toHaveValue("dark");
    expect(screen.getByRole("button", { name: "Chuyển sang giao diện sáng" })).toBeInTheDocument();
    expect(meta.content).toBe("#201d19");
    meta.remove();
  });

  it("still changes theme for this session when browser storage is blocked", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
    applyStoredTheme();
    render(<><ThemeToggle /><ThemeSelector /></>);
    await userEvent.setup().click(screen.getByRole("button", { name: "Chuyển sang giao diện tối" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(screen.getByLabelText("Giao diện")).toHaveValue("dark");
  });
  it("persists the selected theme and applies it to the document", async () => {
    const user = userEvent.setup();
    localStorage.clear();
    render(<ThemeSelector />);
    const select = screen.getByLabelText("Giao diện");
    await user.selectOptions(select, "light");
    expect(localStorage.getItem("playroom:theme")).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("uses the device theme without leaving a forced dark data attribute", async () => {
    const user = userEvent.setup();
    document.documentElement.dataset.theme = "dark";
    render(<ThemeSelector />);
    await user.selectOptions(screen.getByLabelText("Giao diện"), "system");
    expect(document.documentElement.dataset.theme).toBeUndefined();
  });

  it("applies a stored choice before the settings control mounts", () => {
    localStorage.setItem("playroom:theme", "light");
    document.documentElement.dataset.theme = "dark";
    applyStoredTheme();
    expect(document.documentElement.dataset.theme).toBe("light");
  });
});
