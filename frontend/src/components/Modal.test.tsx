import React from "react";
import { describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Modal } from "./Modal";

describe("Modal", () => {
  it("does not mount hidden content before its first open", async () => {
    const user = userEvent.setup();
    function Fixture() {
      const [open, setOpen] = React.useState(false);
      return <><button onClick={() => setOpen(true)}>Open import</button><Modal open={open} title="Import" onClose={() => setOpen(false)}><div data-testid="private-form">Local form</div></Modal></>;
    }
    render(<Fixture />);
    expect(screen.queryByTestId("private-form")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open import" }));
    expect(await screen.findByTestId("private-form")).toBeInTheDocument();
  });

  it("isolates the background, contains keyboard focus and restores the exact trigger", async () => {
    const user = userEvent.setup();
    function Fixture() {
      const [open, setOpen] = React.useState(false);
      return <div data-testid="background">
        <button onClick={() => setOpen(true)}>Open settings</button>
        <button>Background action</button>
        <Modal open={open} title="Settings" onClose={() => setOpen(false)}>
          <fieldset disabled><button>Disabled field</button></fieldset>
          <details><summary>Advanced</summary><button>Collapsed field</button></details>
          <button>First field</button><button>Last field</button><button hidden>Hidden last field</button>
        </Modal>
      </div>;
    }
    render(<Fixture />);
    const trigger = screen.getByRole("button", { name: "Open settings" });
    await user.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: "Settings" });
    expect(document.body.style.overflow).toBe("hidden");
    expect(screen.getByTestId("background").parentElement?.hasAttribute("inert")).toBe(true);
    expect(dialog.contains(document.activeElement)).toBe(true);
    await user.keyboard("{Shift>}{Tab}{/Shift}");
    expect(screen.getByRole("button", { name: "Last field" })).toHaveFocus();
    await user.keyboard("{Tab}");
    expect(screen.getByRole("button", { name: "Đóng" })).toHaveFocus();
    await user.keyboard("{Tab}");
    expect(screen.getByText("Advanced")).toHaveFocus();
    await user.keyboard("{Tab}");
    expect(screen.getByRole("button", { name: "First field" })).toHaveFocus();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(document.body.style.overflow).toBe("");
    expect(screen.getByTestId("background").parentElement?.hasAttribute("inert")).toBe(false);
  });
});

