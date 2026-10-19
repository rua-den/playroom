import userEvent from "@testing-library/user-event";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CustomProviderForm } from "./CustomProviderForm";
import { ToastProvider } from "./Toast";
import type { ModelProfileSummary } from "../api/types";

const profile: ModelProfileSummary = { id: "custom-1", version: 1, provider: "custom", endpoint: "http://127.0.0.1:1234/v1/chat/completions", model: "fixture", secret_version: "cred-1", custom_billing: "provider_managed", limits_source: "application_default", pricing_verified: false };
const saved = { ...profile, profile_hash: "hash" };
function renderForm(initial?: ModelProfileSummary) { return render(<ToastProvider><CustomProviderForm profile={initial} onSaved={vi.fn()} /></ToastProvider>); }

describe("CustomProviderForm", () => {
  it("saves only endpoint, model, and optional credential reference", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(saved), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup(); renderForm();
    await user.type(screen.getByLabelText("Endpoint URL"), "http://127.0.0.1:1234/v1");
    await user.type(screen.getByLabelText("Model ID"), "fixture");
    await user.click(screen.getByRole("button", { name: "Lưu custom provider" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/provider/profiles/custom", expect.objectContaining({ method: "POST" })));
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body).toEqual({ endpoint: "http://127.0.0.1:1234/v1", model: "fixture" });
    expect(body).not.toHaveProperty("context_limit");
    expect(body).not.toHaveProperty("pricing");
    expect(await screen.findByRole("status")).toHaveTextContent("Đã lưu cấu hình custom provider");
  });

  it("stores a typed key once, clears it immediately, and reuses it when profile save retries", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "cred-2", masked: "***123" }), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "temporary" }), { status: 500 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(saved), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock); const user = userEvent.setup(); renderForm();
    await user.type(screen.getByLabelText("Endpoint URL"), "https://relay.example.test/v1"); await user.type(screen.getByLabelText("Model ID"), "fixture"); await user.type(screen.getByLabelText("API key (optional)"), "secret-value");
    await user.click(screen.getByRole("button", { name: "Lưu custom provider" }));
    expect(screen.getByLabelText("API key (optional)")).toHaveValue("");
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Lưu custom provider" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(JSON.parse(fetchMock.mock.calls[2][1].body)).toMatchObject({ credential_id: "cred-2" });
    expect(fetchMock.mock.calls.filter((call) => call[0] === "/api/provider/credentials")).toHaveLength(1);
  });

  it("hydrates a saved key reference without exposing the key and clears it on origin change", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(saved), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock); const user = userEvent.setup(); renderForm(profile);
    expect(await screen.findByDisplayValue(profile.endpoint!)).toBeInTheDocument();
    expect(screen.getByLabelText("API key (optional)")).toHaveAttribute("placeholder", "Đã lưu key; để trống để giữ key");
    await user.clear(screen.getByLabelText("Endpoint URL")); await user.type(screen.getByLabelText("Endpoint URL"), "https://other.example.test/v1");
    await user.type(screen.getByLabelText("Model ID"), "-next"); await user.click(screen.getByRole("button", { name: "Lưu custom provider" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).not.toHaveProperty("credential_id");
  });

  it("disables all fields while the save acknowledgement is pending", async () => {
    let resolve!: (response: Response) => void; const pending = new Promise<Response>((r) => { resolve = r; });
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(pending)); const user = userEvent.setup(); renderForm();
    await user.type(screen.getByLabelText("Endpoint URL"), "https://relay.example.test/v1"); await user.type(screen.getByLabelText("Model ID"), "fixture"); await user.click(screen.getByRole("button", { name: "Lưu custom provider" }));
    expect(screen.getByLabelText("Endpoint URL")).toBeDisabled(); expect(screen.getByLabelText("Model ID")).toBeDisabled(); resolve(new Response(JSON.stringify(saved), { status: 201 }));
  });
});
