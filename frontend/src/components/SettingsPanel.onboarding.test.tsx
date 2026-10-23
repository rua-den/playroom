import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SettingsPanel } from "./SettingsPanel";

describe("Settings onboarding", () => {
  it.each([
    [[], [], {}, "Lưu khóa API"],
    [[{ id: "key", masked: "***" }], [], {}, "Xác minh model"],
    [[{ id: "key", masked: "***" }], [{ id: "p", version: 1, provider: "openrouter", model: "model" }], {}, "Chọn và lưu model narrator"],
    [[{ id: "key", masked: "***" }], [{ id: "p", version: 1, provider: "ollama", model: "model" }], { narrator: { id: "p", version: 1 } }, "Free only đang chặn narrator"],
  ])("shows the next setup step from saved state", async (credentials, profiles, roles, next) => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(Response.json(credentials))
      .mockResolvedValueOnce(Response.json(profiles))
      .mockResolvedValueOnce(Response.json({ mode: "economy", policy: "free_only", roles, budgets: {} })));
    render(<SettingsPanel />);
    expect(await screen.findByRole("note", { name: "Bước tiếp theo" })).toHaveTextContent(next as string);
  });

  it("validates a future local expiry and sends UTC only after explicit consent", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(Response.json([]))
      .mockResolvedValueOnce(Response.json([{ id: "p", version: 1, provider: "ollama", model: "model" }]))
      .mockResolvedValueOnce(Response.json({ mode: "economy", policy: "capped_paid", roles: { narrator: { id: "p", version: 1 } }, budgets: {} }))
      .mockResolvedValueOnce(Response.json({ id: "trial", state: "active" }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<SettingsPanel />);
    const expiry = await screen.findByLabelText("Hết hạn (giờ địa phương)");
    expect(expiry).toHaveAttribute("type", "datetime-local");
    await user.click(screen.getByLabelText(/Tôi chấp thuận hạn mức phiên trả phí/));
    await user.click(screen.getByRole("button", { name: "Chấp thuận ngân sách phiên" }));
    expect(await screen.findByText("Chọn thời điểm hết hạn trong tương lai theo giờ địa phương.")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(3);
    fireEvent.change(expiry, { target: { value: "2020-01-01T12:30" } });
    await user.click(screen.getByRole("button", { name: "Chấp thuận ngân sách phiên" }));
    expect(fetchMock).toHaveBeenCalledTimes(3);
    fireEvent.change(expiry, { target: { value: "2099-01-01T12:30" } });
    await user.click(screen.getByRole("button", { name: "Chấp thuận ngân sách phiên" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
    expect(JSON.parse(fetchMock.mock.calls[3][1].body).expires_at).toBe(new Date("2099-01-01T12:30").toISOString());
  });
});
