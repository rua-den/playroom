import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SettingsPanel } from "./SettingsPanel";
import { ToastProvider } from "./Toast";

describe("SettingsPanel", () => {
  it("shows the three-field custom form and provider-managed cost copy", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([])))
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: "custom-1", version: 1, provider: "custom", model: "local", endpoint: "http://127.0.0.1:1234/v1/chat/completions", pricing_verified: false, custom_billing: "provider_managed", limits_source: "application_default" }])))
      .mockResolvedValueOnce(new Response(JSON.stringify({ mode: "economy", policy: "free_only", roles: { narrator: { id: "custom-1", version: 1 } }, budgets: {} })));
    vi.stubGlobal("fetch", fetchMock);
    render(<ToastProvider><SettingsPanel /></ToastProvider>);
    await screen.findByRole("heading", { name: "Cài đặt provider" });
    expect(screen.getByLabelText("Provider")).toHaveValue("custom");
    await screen.findByDisplayValue("http://127.0.0.1:1234/v1/chat/completions");
    expect(screen.getByLabelText("Endpoint URL")).toBeInTheDocument();
    expect(screen.getByLabelText("Model ID")).toBeInTheDocument();
    expect(screen.getByLabelText("API key (optional)")).toBeInTheDocument();
    expect(screen.queryByLabelText("OpenRouter API key")).not.toBeInTheDocument();
    expect(screen.getByText(/Chi phí và quota do endpoint quản lý/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Giới hạn USD")).not.toBeInTheDocument();
  });
  it("navigates between settings sections without saving or clearing drafts", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ mode: "economy", policy: "free_only", roles: {}, budgets: {} }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<ToastProvider><SettingsPanel demoMode /></ToastProvider>);
    const secret = await screen.findByLabelText("OpenRouter API key");
    await user.type(secret, "draft-key");
    const callsAfterLoad = fetchMock.mock.calls.length;

    await user.click(screen.getByRole("link", { name: "Chi phí" }));
    await user.click(screen.getByRole("link", { name: "Model" }));
    await user.click(screen.getByRole("link", { name: "Kết nối" }));

    expect(secret).toHaveValue("draft-key");
    expect(screen.getByLabelText("Provider")).toBeInTheDocument();
    expect(screen.getByRole("note", { name: "Chế độ demo tổng hợp" })).toHaveTextContent("không gọi AI thật");
    expect(fetchMock).toHaveBeenCalledTimes(callsAfterLoad);
  });

  it("waits for the budget save acknowledgement before showing success", async () => {
    let resolveSave!: (response: Response) => void;
    const save = new Promise<Response>((resolve) => { resolveSave = resolve; });
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ mode: "economy", policy: "free_only", roles: {}, budgets: {} }), { status: 200 }))
      .mockReturnValueOnce(save));
    const user = userEvent.setup();
    render(<ToastProvider><SettingsPanel /></ToastProvider>);
    await screen.findByRole("heading", { name: "Cài đặt provider" });
    await user.click(screen.getByRole("button", { name: "Lưu ngân sách" }));
    expect(within(screen.getByRole("region", { name: "Thông báo" })).queryByRole("status")).not.toBeInTheDocument();
    resolveSave(new Response(JSON.stringify({ mode: "economy", policy: "free_only", roles: {}, budgets: {} }), { status: 200 }));
    expect(await within(screen.getByRole("region", { name: "Thông báo" })).findByRole("status")).toHaveTextContent("Ngân sách");
  });

  it("preserves the draft and shows only generic toast feedback when save fails", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ mode: "economy", policy: "free_only", roles: {}, budgets: {} }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "private server detail" }), { status: 409 })));
    const user = userEvent.setup();
    render(<ToastProvider><SettingsPanel /></ToastProvider>);
    await screen.findByRole("heading", { name: "Cài đặt provider" });
    await user.selectOptions(screen.getByLabelText("Chính sách chi phí"), "capped_paid");
    await user.click(screen.getByText("Nâng cao"));
    await user.type(screen.getByLabelText("Giới hạn USD"), "0.25");
    await user.click(screen.getByRole("button", { name: "Lưu ngân sách" }));
    const toastRegion = screen.getByRole("region", { name: "Thông báo" });
    expect(await within(toastRegion).findByRole("note")).toHaveTextContent("Không thể lưu ngân sách");
    expect(within(toastRegion).getByRole("note")).not.toHaveTextContent("private server detail");
    expect(screen.getByLabelText("Giới hạn USD")).toHaveValue("0.25");
  });

  it("keeps the independent demo note across prop changes and settings saves", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ mode: "economy", policy: "free_only", confirmed_usd_cap: null, roles: {}, budgets: { narrator: { input_limit: 12000, requested_output: 4000, wrapper_buffer: 512 } } }), { status: 200 }))
      .mockResolvedValue(new Response(JSON.stringify({ mode: "economy", policy: "free_only", confirmed_usd_cap: null, roles: {}, budgets: { narrator: { input_limit: 12000, requested_output: 4000, wrapper_buffer: 512 } } }), { status: 200 })));
    const view = render(<SettingsPanel demoMode={false} />);
    await screen.findByRole("heading", { name: "Cài đặt provider" });
    view.rerender(<SettingsPanel demoMode />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Lưu ngân sách" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Ngân sách");
    expect(screen.getByRole("note", { name: "Chế độ demo tổng hợp" })).toBeInTheDocument();
    expect(screen.getByRole("note", { name: "Chế độ demo tổng hợp" })).toHaveTextContent("không thay đổi demo");
    view.rerender(<SettingsPanel demoMode={false} />);
    expect(screen.queryByRole("note", { name: "Chế độ demo tổng hợp" })).not.toBeInTheDocument();
  });
  it("stores a credential once, clears the secret input, and only renders masked credentials", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: "cred-1", masked: "sk-••••1234" }]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ mode: "economy", policy: "free_only", roles: {}, budgets: {} }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "cred-2", masked: "sk-••••5678" }), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<SettingsPanel />);
    const secret = await screen.findByLabelText("OpenRouter API key");
    await user.type(secret, "sk-secret-value");
    await user.click(screen.getByRole("button", { name: "Lưu credential" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/provider/credentials", expect.objectContaining({ method: "POST", body: JSON.stringify({ secret: "sk-secret-value" }) })));
    expect(secret).toHaveValue("");
    expect(screen.queryByText("sk-secret-value")).not.toBeInTheDocument();
  });

  it("disables credential save while the request is pending", async () => {
    let resolveCredential!: (response: Response) => void;
    const credentialRequest = new Promise<Response>((resolve) => {
      resolveCredential = resolve;
    });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ mode: "economy", policy: "free_only", roles: {}, budgets: {} }), { status: 200 }))
      .mockReturnValueOnce(credentialRequest);
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<SettingsPanel />);
    const secret = await screen.findByLabelText("OpenRouter API key");
    await user.type(secret, "sk-secret-value");
    const save = screen.getByRole("button", { name: "Lưu credential" });
    await user.click(save);
    expect(save).toBeDisabled();
    expect(secret).toBeDisabled();
    await user.click(save);
    expect(fetchMock.mock.calls.filter((call) => call[0] === "/api/provider/credentials" && call[1]?.method === "POST")).toHaveLength(1);
    resolveCredential(new Response(JSON.stringify({ id: "cred-2", masked: "sk-••••5678" }), { status: 201 }));
    await waitFor(() => expect(save).not.toBeDisabled());
  });

  it("focuses credential errors, keeps the draft, and re-enables the fieldset", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ mode: "economy", policy: "free_only", roles: {}, budgets: {} }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "credential rejected" }), { status: 400 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "credential rejected" }), { status: 400 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<SettingsPanel />);
    const secret = await screen.findByLabelText("OpenRouter API key");
    await user.type(secret, "sk-secret-value");
    await user.click(screen.getByRole("button", { name: "Lưu credential" }));
    const error = await screen.findByRole("alert", { name: "Lỗi cài đặt" });
    expect(error).toHaveFocus();
    expect(secret).toHaveValue("sk-secret-value");
    expect(secret).not.toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Lưu credential" }));
    await waitFor(() => expect(error).toHaveFocus());
  });

  it("saves budget and policy without changing pinned role IDs, while explicit model switch sends the selected role", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: "profile-1", version: 2, model: "old/model", provider: "openrouter", output_limit: 4000, credential_tier: "free", pricing_verified: true, pricing: { prompt: "0.000001", completion: "0.000002", currency: "USD", unit: "USD/token" }, credential_metadata: { free_model_daily_requests: 50 }, structured_output: true, native_structured_output: true, structured_schema_parameter: "response_format" }, { id: "profile-2", version: 1, model: "new/model", provider: "openrouter", output_limit: 4000, credential_tier: "free", structured_output: true, native_structured_output: true, structured_schema_parameter: "response_format" }]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ mode: "economy", policy: "free_only", confirmed_usd_cap: null, roles: { narrator: { id: "profile-1", version: 1, profile_hash: "hash-v1" } }, budgets: { narrator: { input_limit: 12000, requested_output: 4000, wrapper_buffer: 512 } } }), { status: 200 }))
      .mockResolvedValue(new Response(JSON.stringify({ settings_revision: 2 }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<SettingsPanel />);
    await screen.findAllByRole("option", { name: /old\/model/ });
    expect(screen.getByText(/Đang ghim.*v1.*hash-v1/)).toBeInTheDocument();
    expect(screen.getByLabelText("Model narrator")).toHaveValue("");
    await user.selectOptions(screen.getByLabelText("Chính sách chi phí"), "capped_paid");
    await user.click(screen.getByText("Nâng cao"));
    await user.type(screen.getByLabelText("Giới hạn USD"), "1");
    await user.clear(screen.getByLabelText("Narrator input tokens")); await user.type(screen.getByLabelText("Narrator input tokens"), "9000");
    await user.click(screen.getByRole("button", { name: "Lưu ngân sách" }));
    const budgetBody = JSON.parse(fetchMock.mock.calls.at(-1)![1].body as string);
    expect(budgetBody).toMatchObject({ policy: "capped_paid", confirmed_usd_cap: "1", budgets: { narrator: { input_limit: 9000 } } });
    expect(budgetBody).not.toHaveProperty("narrator_profile_id");
    await user.selectOptions(screen.getByLabelText("Model narrator"), "profile-1");
    await user.click(screen.getByRole("button", { name: "Đổi model narrator" }));
    const switchBody = JSON.parse(fetchMock.mock.calls.at(-1)![1].body as string);
    expect(switchBody).toMatchObject({ narrator_profile_id: "profile-1" });
  });

  it("shows verified pricing and provider quota metadata, or unknown when absent", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: "p1", version: 1, model: "priced/model", provider: "openrouter", credential_tier: "free", pricing_verified: true, pricing: { prompt: "0.1", completion: "0.2", currency: "USD", unit: "USD/token" }, credential_metadata: { free_model_daily_requests: 42, quota_period: "day", quota_source: "provider" }, structured_output: true, native_structured_output: true, structured_schema_parameter: "response_format" }, { id: "p2", version: 1, model: "partial/model", provider: "openrouter", native_structured_output: true }]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ mode: "economy", policy: "free_only", roles: {}, budgets: {} }), { status: 200 })));
    render(<SettingsPanel />);
    await screen.findByText(/prompt: 0\.1/);
    expect(screen.getByText(/prompt: 0.1/)).toBeInTheDocument();
    expect(screen.getByText(/free quota: 42/)).toBeInTheDocument();
    expect(screen.getByText(/free quota: 42.*day.*provider/)).toBeInTheDocument();
    expect(screen.getByText(/schema: native strict/)).toBeInTheDocument();
    expect(screen.getByText(/partial\/model.*schema: unknown.*pricing: unknown.*free quota: unknown/)).toBeInTheDocument();
    expect(screen.getByText(/pricing: prompt: 0\.1, completion: 0\.2 USD\/token/)).toBeInTheDocument();
  });

  it("keeps credential and paid-cap drafts visible when the server rejects them", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ mode: "economy", policy: "free_only", confirmed_usd_cap: null, roles: {}, budgets: {} }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "A confirmed USD cap is required" }), { status: 409 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<SettingsPanel />);
    await screen.findByLabelText("OpenRouter API key");
    await user.selectOptions(screen.getByLabelText("Chính sách chi phí"), "capped_paid");
    await user.click(screen.getByText("Nâng cao"));
    await user.type(screen.getByLabelText("Giới hạn USD"), "0");
    await user.click(screen.getByRole("button", { name: "Lưu ngân sách" }));
    expect(screen.getByLabelText("Giới hạn USD")).toHaveValue("0");
    expect(await screen.findByRole("alert")).toHaveTextContent("confirmed USD cap");
  });

  it("clears a verification error after a successful retry", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: "cred-1", masked: "sk-••••1234" }]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ mode: "economy", policy: "free_only", roles: {}, budgets: {} }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "verification failed" }), { status: 502 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "p1", version: 1, model: "verified/model", provider: "openrouter", pricing_verified: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<SettingsPanel />);
    await screen.findByLabelText("Model ID");
    await user.selectOptions(screen.getByLabelText("Credential"), "cred-1");
    await user.type(screen.getByLabelText("Model ID"), "verified/model");
    await user.type(screen.getByLabelText("Provider tag"), "openrouter");
    await user.click(screen.getByRole("button", { name: "Xác minh profile" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Xác minh profile" }));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });

  it("keeps every settings input touch reachable", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ mode: "economy", policy: "free_only", roles: {}, budgets: {} }), { status: 200 })));
    render(<SettingsPanel />);
    const panel = await screen.findByRole("region", { name: "Cài đặt provider" });
    expect(Array.from(panel.querySelectorAll("input, select, textarea")).every((control) => control.classList.contains("touch-target"))).toBe(true);
  });

  it("keeps the required paid cap visible while optional token metadata is advanced", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ mode: "economy", policy: "capped_paid", confirmed_usd_cap: "0.02", roles: {}, budgets: {} }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<SettingsPanel />);
    await screen.findByLabelText("Chính sách chi phí");
    expect(screen.getByLabelText("Giới hạn USD")).toBeVisible();
    expect(screen.getByLabelText("Giới hạn USD")).toHaveValue("0.02");
    expect(screen.getByLabelText("Narrator input tokens")).not.toBeVisible();
    await user.click(screen.getByText("Nâng cao"));
    expect(screen.getByLabelText("Narrator input tokens")).toBeVisible();
  });
});

  it("offers Ollama Cloud credential and fixed model verification without an endpoint field", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ mode: "economy", policy: "free_only", roles: {}, budgets: {} }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<SettingsPanel />);
    await screen.findByLabelText("Provider");
    await userEvent.setup().selectOptions(screen.getByLabelText("Provider"), "ollama");
    expect(screen.getByLabelText("Ollama Cloud API key")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Model Ollama Cloud" })).toHaveValue("gemma4:31b-cloud");
    expect(screen.queryByLabelText("Endpoint")).not.toBeInTheDocument();
  });

  it("verifies Ollama Cloud with the saved credential and fixed model endpoint", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: "cred-1", masked: "ol-••••1234" }]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ mode: "economy", policy: "free_only", roles: {}, budgets: {} }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "ollama-profile", version: 1, model: "gpt-oss:120b-cloud", provider: "ollama" }), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<SettingsPanel />);
    await screen.findByLabelText("Provider");
    await user.selectOptions(screen.getByLabelText("Provider"), "ollama");
    await user.selectOptions(screen.getByLabelText("Credential"), "cred-1");
    await user.selectOptions(screen.getByLabelText("Model Ollama Cloud"), "gpt-oss:120b-cloud");
    await user.click(screen.getByRole("button", { name: "Xác minh profile" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/provider/profiles/verify", expect.objectContaining({ method: "POST", body: JSON.stringify({ provider: "ollama", credential_id: "cred-1", model: "gpt-oss:120b-cloud", endpoint: "https://ollama.com/v1" }) })));
  });


it("requires explicit consent and separates cumulative grant from per-send settings", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify([{ id: "ollama-paid", version: 2, model: "gpt-oss:120b", credential_tier: "paid" }]), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ mode: "economy", policy: "capped_paid", confirmed_usd_cap: "0.05", roles: { narrator: { id: "ollama-paid", version: 2 } }, budgets: {} }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ id: "trial-one", state: "active", total_cap_usd: "0.02", per_send_cap_usd: "0.01", reserved_usd: "0", remaining_usd: "0.02", max_jobs: 2, jobs_used: 0 }), { status: 201 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ id: "trial-one", state: "revoked", total_cap_usd: "0.02", reserved_usd: "0", remaining_usd: "0.02", max_jobs: 2, jobs_used: 0 }), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  render(<SettingsPanel />);
  await screen.findByText("Ngân sách toàn phiên trả phí");
  const approve = screen.getByRole("button", { name: "Chấp thuận ngân sách phiên" });
  expect(approve).toBeDisabled();
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Tổng ngân sách được duyệt (USD)"), "0.02");
  await user.type(screen.getByLabelText("Tối đa mỗi lượt (USD)"), "0.01");
  await user.clear(screen.getByLabelText("Số lượt Send tối đa"));
  await user.type(screen.getByLabelText("Số lượt Send tối đa"), "2");
  await user.type(screen.getByLabelText("Hết hạn (ISO UTC)"), "2026-10-15T12:00:00Z");
  expect(approve).toBeDisabled();
  await user.click(screen.getByLabelText(/Tôi chấp thuận hạn mức phiên trả phí/));
  await user.click(approve);
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/provider/trials", expect.objectContaining({ method: "POST" })));
  const sent = JSON.parse(String(fetchMock.mock.calls[3][1].body));
  expect(sent).toMatchObject({ profile_id: "ollama-paid", profile_version: 2, total_cap_usd: "0.02", per_send_cap_usd: "0.01", max_jobs: 2, expires_at: "2026-10-15T12:00:00Z" });
  expect(await screen.findByText(/Trạng thái: active.*còn 0.02 USD/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Thu hồi phiên trả phí" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/provider/trials/trial-one/revoke", expect.objectContaining({ method: "POST" })));
});


describe("Free-first provider settings", () => {
  it("defaults to a free-first explanation without fabricated usage counts or USD budgets", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ mode: "economy", policy: "free_only", roles: {}, budgets: {} }), { status: 200 })));
    const user = userEvent.setup();
    render(<SettingsPanel />);
    await screen.findByLabelText("Provider");
    expect(screen.queryByText("Chơi với tài khoản Free")).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Provider"), "ollama");
    expect(screen.getByText("Chơi với tài khoản Free")).toBeInTheDocument();
    expect(screen.getByText(/credits miễn phí.*token/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Giới hạn USD")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Số lượt Send tối đa")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Narrator input tokens")).not.toBeInTheDocument();
    expect(screen.queryByText(/50 lượt/)).not.toBeInTheDocument();
  });

  it("warns when a pinned paid Ollama model cannot be used with free-only policy", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: "ollama-p", version: 2, model: "gpt-oss:120b", provider: "ollama", credential_tier: "paid" }]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ mode: "economy", policy: "free_only", roles: { narrator: { id: "ollama-p", version: 2 } }, budgets: {} }), { status: 200 })));
    render(<SettingsPanel />);
    expect(await screen.findByText("Chơi với tài khoản Free")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("gpt-oss:120b");
    expect(screen.getByRole("alert")).toHaveTextContent(/không được xác minh là model miễn phí/);
    expect(screen.queryByLabelText("Số lượt Send tối đa")).not.toBeInTheDocument();
  });

  it("shows advanced token budgets only after opting into paid settings", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ mode: "economy", policy: "free_only", roles: {}, budgets: { narrator: { input_limit: 12000, requested_output: 4000, wrapper_buffer: 512 } } }), { status: 200 })));
    const user = userEvent.setup();
    render(<SettingsPanel />);
    await screen.findByLabelText("Chính sách chi phí");
    expect(screen.queryByLabelText("Narrator input tokens")).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Chính sách chi phí"), "capped_paid");
    expect(screen.getByLabelText("Narrator input tokens")).not.toBeVisible();
    await user.click(screen.getByText("Nâng cao"));
    expect(screen.getByLabelText("Narrator input tokens")).toBeInTheDocument();
    expect(screen.getByLabelText("Số lượt Send tối đa")).toHaveValue(null);
  });
});


it("submits the officially supported Gemma4 starter model by default without inventing free quota", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify([{ id: "cred-1", masked: "ol-•••123" }]), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ mode: "economy", policy: "free_only", roles: {}, budgets: {} }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ id: "gemma-profile", version: 1, model: "gemma4:31b", model_label: "gemma4:31b-cloud", provider: "ollama", credential_tier: "free" }), { status: 201 }));
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup();
  render(<SettingsPanel />);
  await screen.findByLabelText("Provider");
  await user.selectOptions(screen.getByLabelText("Provider"), "ollama");
  await user.selectOptions(screen.getByLabelText("Credential"), "cred-1");
  expect(screen.getByRole("combobox", { name: "Model Ollama Cloud" })).toHaveValue("gemma4:31b-cloud");
  expect(screen.getByText(/credits mua thêm/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Xác minh profile" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/provider/profiles/verify",
    expect.objectContaining({ method: "POST", body: JSON.stringify({
      provider: "ollama", credential_id: "cred-1", model: "gemma4:31b-cloud", endpoint: "https://ollama.com/v1",
    }) })));
  expect(screen.queryByLabelText("Số lượt Send tối đa")).not.toBeInTheDocument();
});


it("explains that Gemma4 starter cannot be sent under Free only when purchased credits may be used", async () => {
  vi.stubGlobal("fetch", vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify([{ id: "starter", version: 1, provider: "ollama", model: "gemma4:31b", model_label: "gemma4:31b-cloud", credential_tier: "free" }]), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ mode: "economy", policy: "free_only", roles: { narrator: { id: "starter", version: 1 } }, budgets: {} }), { status: 200 })));
  render(<SettingsPanel />);
  expect(await screen.findByText("Chơi với tài khoản Free")).toBeInTheDocument();
  const warning = screen.getByRole("alert");
  expect(warning).toHaveTextContent("gemma4:31b");
  expect(warning).toHaveTextContent("Free only sẽ chặn");
  expect(warning).toHaveTextContent("Capped paid");
  expect(screen.queryByLabelText("Số lượt Send tối đa")).not.toBeInTheDocument();
});
