import userEvent from "@testing-library/user-event";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ThemeSelector, applyStoredTheme } from "./ThemeSelector";

describe("ThemeSelector", () => {
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
