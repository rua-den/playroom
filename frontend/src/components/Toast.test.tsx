import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ToastProvider, useToast } from "./Toast";

function Trigger() { const toast = useToast(); return <><button onClick={() => toast.success("Saved")}>success</button><button onClick={() => toast.error("Failed")}>error</button></>; }

describe("ToastProvider", () => {
  it("shows success and error toasts, dismisses manually, and caps the stack", () => {
    render(<ToastProvider><Trigger /></ToastProvider>);
    fireEvent.click(screen.getByText("success")); fireEvent.click(screen.getByText("error"));
    expect(screen.getByRole("region", { name: "Thông báo" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Saved");
    expect(screen.getByRole("note")).toHaveTextContent("Failed");
    fireEvent.click(within(screen.getByRole("status")).getByRole("button", { name: "Đóng thông báo" }));
    expect(screen.queryByRole("status")).toBeNull();
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
});
