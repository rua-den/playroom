import userEvent from "@testing-library/user-event";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ModelSwitcher } from "./ModelSwitcher";

const settings = {
  settings_revision: 7,
  mode: "economy" as const,
  policy: "free_only" as const,
  confirmed_usd_cap: null,
  roles: { narrator: { id: "paid-model", version: 2 } },
  budgets: {},
};

describe("ModelSwitcher", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("loads the pinned verified narrator and saves only after an explicit acknowledgement", async () => {
    const user = userEvent.setup();
    const onSaved = vi.fn();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(settings)))
      .mockResolvedValueOnce(new Response(JSON.stringify([
        { id: "paid-model", version: 2, model: "gpt-oss:120b", model_label: "GPT OSS 120B", provider: "ollama", credential_tier: "paid", pricing_verified: true },
        { id: "old-model", version: 1, model: "old", provider: "openrouter", credential_tier: "free", pricing_verified: true },
      ])))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...settings, roles: { narrator: { id: "old-model", version: 1 } } })));
    vi.stubGlobal("fetch", fetchMock);
    render(<ModelSwitcher open onClose={vi.fn()} onOpenCostSettings={vi.fn()} onSaved={onSaved} busy={false} />);
    await waitFor(() => expect(screen.getByText("GPT OSS 120B")).toBeInTheDocument());
    expect(screen.getByText(/Free only/)).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Model narrator"), "old-model");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await user.click(screen.getByRole("button", { name: "Lưu model" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(fetchMock.mock.calls[2][1]?.method).toBe("PUT");
    expect(JSON.parse(String(fetchMock.mock.calls[2][1]?.body))).toEqual({ narrator_profile_id: "old-model" });
    expect(onSaved).toHaveBeenCalledOnce();
  });

  it("does not save while the composer is busy and offers cost settings", async () => {
    const onOpenCostSettings = vi.fn();
    render(<ModelSwitcher open onClose={vi.fn()} onOpenCostSettings={onOpenCostSettings} onSaved={vi.fn()} busy />);
    expect(screen.getByRole("button", { name: "Lưu model" })).toBeDisabled();
    await userEvent.setup().click(screen.getByRole("button", { name: /Cài đặt chi phí/ }));
    expect(onOpenCostSettings).toHaveBeenCalledOnce();
  });

  it("filters synthetic and unverified profiles while warning about Ollama spending lockout", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...settings, roles: { narrator: { id: "paid-model", version: 2 } } })))
      .mockResolvedValueOnce(new Response(JSON.stringify([
        { id: "fake", version: 1, model: "fake-demo", provider: "openrouter", pricing_verified: true },
        { id: "unverified", version: 1, model: "hidden", provider: "openrouter", pricing_verified: false },
        { id: "paid-model", version: 2, model: "gpt-oss:120b", model_label: "GPT OSS 120B", provider: "ollama", credential_tier: "free", pricing_verified: true },
      ])));
    vi.stubGlobal("fetch", fetchMock);
    render(<ModelSwitcher open onClose={vi.fn()} onOpenCostSettings={vi.fn()} onSaved={vi.fn()} busy={false} />);
    await waitFor(() => expect(screen.getByRole("option", { name: /GPT OSS/ })).toBeInTheDocument());
    expect(screen.queryByRole("option", { name: /fake-demo/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /hidden/ })).not.toBeInTheDocument();
    expect(screen.getByText(/included credits chưa chứng minh/)).toBeInTheDocument();
  });

  it("ignores a deferred save rejection after the modal unmounts", async () => {
    let rejectSave: (error: Error) => void = () => undefined;
    const savePromise = new Promise<Response>((_, reject) => { rejectSave = reject; });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(settings)))
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: "old-model", version: 1, model: "old", provider: "openrouter", pricing_verified: true }])))
      .mockReturnValueOnce(savePromise);
    vi.stubGlobal("fetch", fetchMock);
    const view = render(<ModelSwitcher open onClose={vi.fn()} onOpenCostSettings={vi.fn()} onSaved={vi.fn()} busy={false} />);
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByRole("option", { name: /old/ })).toBeInTheDocument());
    await user.selectOptions(screen.getByLabelText("Model narrator"), "old-model");
    await user.click(screen.getByRole("button", { name: "Lưu model" }));
    view.unmount();
    rejectSave(new Error("late failure"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
  });

  it("keeps the selected model visible after an acknowledged save failure", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(settings)))
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: "old-model", version: 1, model: "old", provider: "openrouter", pricing_verified: true }])))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "rejected" }), { status: 422 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<ModelSwitcher open onClose={vi.fn()} onOpenCostSettings={vi.fn()} onSaved={vi.fn()} busy={false} />);
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByRole("option", { name: /old/ })).toBeInTheDocument());
    const select = screen.getByLabelText("Model narrator");
    await user.selectOptions(select, "old-model");
    await user.click(screen.getByRole("button", { name: "Lưu model" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("bản nháp vẫn được giữ"));
    expect(select).toHaveValue("old-model");
  });
});
