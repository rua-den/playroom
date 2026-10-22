import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { Modal } from "./Modal";
import { ToastProvider, useToast } from "./Toast";

function Trigger() { const toast = useToast(); return <><button onClick={() => toast.success("Saved")}>success</button><button onClick={() => toast.error("Failed")}>error</button></>; }
function CaptureApi({ apis }: { apis: Array<ReturnType<typeof useToast>> }) { apis.push(useToast()); return null; }

describe("ToastProvider", () => {
  it("shows success and error toasts, dismisses manually, and caps the stack", () => {
    render(<ToastProvider><Trigger /></ToastProvider>);
    fireEvent.click(screen.getByText("success")); fireEvent.click(screen.getByText("error"));
    expect(screen.getByRole("note")).toHaveTextContent("Failed");
    fireEvent.click(screen.getByText("success")); fireEvent.click(screen.getByText("success")); fireEvent.click(screen.getByText("success")); fireEvent.click(screen.getByText("success")); fireEvent.click(screen.getByText("success"));
    expect(screen.getByRole("region", { name: "Thông báo" })).toBeInTheDocument();
    expect(screen.getAllByRole("status")).toHaveLength(3);
    expect(screen.getAllByRole("status").length + screen.queryAllByRole("note").length).toBeLessThanOrEqual(3);
    fireEvent.click(within(screen.getAllByRole("status")[0]).getByRole("button", { name: "Đóng thông báo" }));
    expect(screen.getAllByRole("status")).toHaveLength(2);
  });

  it("keeps the timer paused when focus remains inside while hover ends", () => {
    vi.useFakeTimers();
    render(<ToastProvider><Trigger /></ToastProvider>);
    fireEvent.click(screen.getByText("success"));
    const toast = screen.getByRole("status");
    fireEvent.mouseEnter(toast); fireEvent.focus(toast); fireEvent.mouseLeave(toast);
    act(() => { vi.advanceTimersByTime(6000); });
    expect(screen.getByRole("status")).toBeInTheDocument();
    fireEvent.blur(toast, { relatedTarget: document.body });
    act(() => { vi.advanceTimersByTime(5000); });
    expect(screen.queryByRole("status")).toBeNull();
    vi.useRealTimers();
  });

  it("pauses success dismissal while focused", () => {
    vi.useFakeTimers();
    render(<ToastProvider><Trigger /></ToastProvider>);
    fireEvent.click(screen.getByText("success"));
    const toast = screen.getByRole("status");
    fireEvent.focus(toast); act(() => { vi.advanceTimersByTime(6000); }); expect(screen.getByRole("status")).toBeInTheDocument();
    fireEvent.blur(toast); act(() => { vi.advanceTimersByTime(5000); }); expect(screen.queryByRole("status")).toBeNull();
    vi.useRealTimers();
  });

  it("preserves the remaining dismissal time across overlapping focus and hover pauses", () => {
    vi.useFakeTimers();
    try {
      render(<ToastProvider><Trigger /></ToastProvider>);
      fireEvent.click(screen.getByText("success"));
      const toast = screen.getByRole("status");
      const closeButton = within(toast).getByRole("button");
      act(() => { vi.advanceTimersByTime(4900); });
      fireEvent.mouseEnter(toast);
      act(() => closeButton.focus());
      act(() => { vi.advanceTimersByTime(6000); });
      expect(screen.getByRole("status")).toBeInTheDocument();
      act(() => closeButton.blur());
      act(() => { vi.advanceTimersByTime(6000); });
      expect(screen.getByRole("status")).toBeInTheDocument();
      fireEvent.mouseLeave(toast);
      act(() => { vi.advanceTimersByTime(99); });
      expect(screen.getByRole("status")).toBeInTheDocument();
      act(() => { vi.advanceTimersByTime(1); });
      expect(screen.queryByRole("status")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("isolates a remounted owner from late calls through the previous toast API", () => {
    const apis: Array<ReturnType<typeof useToast>> = [];
    function Harness() {
      const [owner, setOwner] = useState("ownerA");
      return <><button onClick={() => setOwner("ownerB")}>switch owner</button><ToastProvider key={owner}><CaptureApi apis={apis} /><Trigger /></ToastProvider></>;
    }
    render(<Harness />);
    const oldApi = apis[0];
    fireEvent.click(screen.getByText("switch owner"));
    expect(apis.length).toBeGreaterThan(1);
    act(() => oldApi.success("Late stale toast"));
    expect(screen.getByRole("region", { name: "Thông báo" })).not.toHaveTextContent("Late stale toast");
    fireEvent.click(screen.getByText("success"));
    expect(screen.getByRole("status")).toHaveTextContent("Saved");
  });

  it("relocates the stack into the topmost modal and restores the body outlet without losing actions", async () => {
    const undo = vi.fn();
    function Fixture() {
      const [firstOpen, setFirstOpen] = useState(false);
      const [secondOpen, setSecondOpen] = useState(false);
      const toast = useToast();
      return <>
        <button onClick={() => setFirstOpen(true)}>open first</button>
        <button onClick={() => toast.success("Saved", { label: "Undo", onClick: undo })}>save</button>
        <Modal open={firstOpen} title="First" onClose={() => setFirstOpen(false)}>
          <button onClick={() => setSecondOpen(true)}>open second</button>
          <Modal open={secondOpen} title="Second" onClose={() => setSecondOpen(false)}><p>Second body</p></Modal>
        </Modal>
      </>;
    }
    render(<ToastProvider><Fixture /></ToastProvider>);
    fireEvent.click(screen.getByRole("button", { name: "open first" }));
    fireEvent.click(screen.getByRole("button", { name: "save" }));
    await waitFor(() => expect(screen.getByRole("region", { name: "Thông báo" }).closest(".modal-toast-outlet")).toBeInTheDocument());
    const firstOutlet = screen.getByRole("region", { name: "Thông báo" }).parentElement;
    const firstDialog = screen.getByRole("dialog", { name: "First" });
    expect(firstDialog.querySelector("h2")).toHaveTextContent("First");
    await within(screen.getByRole("dialog", { name: "First" })).findByRole("button", { name: "open second" }).then((button) => fireEvent.click(button));
    await waitFor(() => expect(screen.getByRole("dialog", { name: "Second" })).toBeInTheDocument());
    expect(screen.getByRole("region", { name: "Thông báo" }).closest(".app-modal")).not.toBe(firstDialog);
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(undo).toHaveBeenCalledTimes(1);
    fireEvent.click(within(screen.getByRole("dialog", { name: "Second" })).getByRole("button", { name: "Đóng" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Second" })).not.toBeInTheDocument());
    expect(screen.queryByRole("status")).toBeNull();
    fireEvent.click(within(screen.getByRole("dialog", { name: "First" })).getByRole("button", { name: "Đóng" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "First" })).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "save" }));
    await waitFor(() => expect(screen.getByRole("region", { name: "Thông báo" }).closest(".toast-portal-host")?.parentElement).toBe(document.body));
  });

  it("preserves a pending undo while the modal outlet moves and rejects a second invocation", async () => {
    let resolveUndo!: () => void;
    const undo = vi.fn(() => new Promise<void>((resolve) => { resolveUndo = resolve; }));
    function Fixture() {
      const [open, setOpen] = useState(false);
      const toast = useToast();
      return <>
        <button onClick={() => toast.success("Saved", { label: "Undo", onClick: undo })}>save pending</button>
        <button onClick={() => setOpen(true)}>open modal</button>
        <Modal open={open} title="Pending" onClose={() => setOpen(false)}><p>Modal body</p></Modal>
      </>;
    }
    render(<ToastProvider><Fixture /></ToastProvider>);
    fireEvent.click(screen.getByRole("button", { name: "save pending" }));
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    const undoButton = screen.getByRole("button", { name: "Đang xử lý…" });
    expect(undo).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "open modal" }));
    await waitFor(() => expect(screen.getByRole("dialog", { name: "Pending" })).toBeVisible());
    expect(screen.getByRole("region", { name: "Thông báo" }).closest("[inert]")).toBeNull();
    expect(screen.getByRole("button", { name: "Đang xử lý…" })).toBeDisabled();
    const pendingDialog = screen.getByRole("dialog", { name: "Pending" });
    fireEvent.click(within(pendingDialog).getByRole("button", { name: "Đóng" }));
    await waitFor(() => expect(pendingDialog).not.toBeVisible());
    expect(screen.getByRole("region", { name: "Thông báo" }).closest("[inert]")).toBeNull();
    expect(screen.getByRole("button", { name: "Đang xử lý…" })).toBe(undoButton);
    fireEvent.click(undoButton);
    expect(undo).toHaveBeenCalledTimes(1);
    resolveUndo();
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
  });
});
