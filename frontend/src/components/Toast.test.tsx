import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
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
});
