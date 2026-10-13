import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SettingsPanel } from "./SettingsPanel";

describe("SettingsPanel", () => {
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
});
