import userEvent from "@testing-library/user-event";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { GenerationComposer, mergeGenerationEvents, generationIdentityKey } from "./GenerationComposer";
import type { CampaignProjection } from "../api/types";

const projection = { campaign: { id: "campaign-1", title: "Test", created_at: "", updated_at: "", archived_at: null }, branch: { id: "branch-1", name: "main", state_version: 3, checkpoint_id: "checkpoint-1" }, checkpoint: { id: "checkpoint-1", state_version: 3, parent_checkpoint_id: null, selected_revision_ids: [], retrieval_policy: "auto" }, profiles: {}, scene: null, transcript: [], jobs: [] } as CampaignProjection;

describe("GenerationComposer", () => {
  it("deduplicates UTF-16 deltas and reports a gap for authoritative content recovery", () => {
    expect(mergeGenerationEvents("A", 1, [{ id: 1, stage: "narration", event_type: "delta", offset: 3, content: "😀" }, { id: 2, stage: "narration", event_type: "delta", offset: 3, content: "😀" }])).toEqual({ text: "A😀", offset: 3, gap: false });
    expect(mergeGenerationEvents("A", 1, [{ id: 1, stage: "narration", event_type: "delta", offset: 4, content: "B" }]).gap).toBe(true);
  });

  it("persists preview identity before generate and recovers an ambiguous POST by key", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "preview-1", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", action: "Đi tiếp", status: "ready", profile_id: "profile-1" }), { status: 201 }))
      .mockImplementationOnce((_input, init) => { expect(localStorage.getItem(generationIdentityKey("owner-1", "campaign-1", "branch-1"))).toContain("preview-1"); return Promise.reject(new TypeError("connection reset")); })
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "job-1", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "queued", draft: "", offset: 0, offset_unit: "utf16_code_units" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={vi.fn()} />);
    await user.type(screen.getByLabelText("Hành động tiếp theo"), "Đi tiếp");
    await user.click(screen.getByRole("button", { name: "Kể tiếp" }));
    expect(await screen.findByText("Giai đoạn: queued")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("keeps the durable identity through a temporary recovery failure", async () => {
    const saved = { ownerId: "owner-1", campaignId: "campaign-1", branchId: "branch-1", checkpointId: "checkpoint-1", action: "Tiếp tục", previewId: "preview-1", idempotencyKey: "key-1" };
    localStorage.setItem(generationIdentityKey("owner-1", "campaign-1", "branch-1"), JSON.stringify(saved));
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("khôi phục");
    expect(localStorage.getItem(generationIdentityKey("owner-1", "campaign-1", "branch-1"))).toContain("key-1");
  });

  it("does not treat an empty event response as terminal completion", async () => {
    const saved = { ownerId: "owner-1", campaignId: "campaign-1", branchId: "branch-1", checkpointId: "checkpoint-1", action: "Tiếp tục", previewId: "preview-1", idempotencyKey: "key-1", jobId: "job-1" };
    localStorage.setItem(generationIdentityKey("owner-1", "campaign-1", "branch-1"), JSON.stringify(saved));
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...saved, status: "running", draft: "", offset: 0, offset_unit: "utf16_code_units" })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ events: [] }))));
    render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Giai đoạn: running")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Commit ứng viên" })).toBeDisabled();
  });

  it("recovers an owned projected job after local client cache is cleared without generating again", async () => {
    localStorage.clear();
    const projected: CampaignProjection = { ...projection, jobs: [{ id: "job-2", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "running", mode: "economy", action: "Tiếp tục", created_at: "", cancel_requested: false }] };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "job-2", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "running", action: "Tiếp tục", draft: "", offset: 0, offset_unit: "utf16_code_units", attempt_counts_by_stage: { narration: { dispatched: 1 } }, cost_ledger: { stages: { narration: { actual_status: "unknown" } } } })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ events: [] })));
    vi.stubGlobal("fetch", fetchMock);
    render(<GenerationComposer ownerId="owner-1" projection={projected} profileId="profile-1" onCommitted={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Giai đoạn: running")).toBeInTheDocument());
    expect(fetchMock).not.toHaveBeenCalledWith(expect.stringContaining("/generate"), expect.objectContaining({ method: "POST" }));
    expect(screen.getByText(/Chi phí narration: provider unknown/)).toBeInTheDocument();
  });

  it("does not generate from a stale projection when commit refresh fails", async () => {
    localStorage.clear();
    const saved = { ownerId: "owner-1", campaignId: "campaign-1", branchId: "branch-1", checkpointId: "checkpoint-1", action: "Cũ", previewId: "preview-1", idempotencyKey: "key-1", jobId: "job-3" };
    localStorage.setItem(generationIdentityKey("owner-1", "campaign-1", "branch-1"), JSON.stringify(saved));
    const fetchMock = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ id: "job-3", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "candidate", draft: "Kết quả", offset: 7, offset_unit: "utf16_code_units" }))).mockResolvedValueOnce(new Response(JSON.stringify({ ok: true })));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={vi.fn().mockResolvedValue(undefined)} />);
    const actionField = await screen.findByLabelText("Hành động tiếp theo");
    await user.clear(actionField);
    await user.type(actionField, "Mới");
    await user.click(screen.getByRole("button", { name: "Commit và kể tiếp" }));
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/context/previews"))).toBe(false);
    expect(screen.getByDisplayValue("Mới")).toBeInTheDocument();
  });

  it("restores the submitted action from durable recovery identity", async () => {
    localStorage.clear();
    localStorage.setItem(generationIdentityKey("owner-1", "campaign-1", "branch-1"), JSON.stringify({ ownerId: "owner-1", campaignId: "campaign-1", branchId: "branch-1", checkpointId: "checkpoint-1", action: "Đã lưu hành động", previewId: "preview-1", idempotencyKey: "key-1", jobId: "job-4" }));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: "job-4", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "failed", action: "Đã lưu hành động", draft: "Bản nháp", offset: 8, offset_unit: "utf16_code_units", failure: { code: "GENERATION_FAILED" } }))));
    render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={vi.fn()} />);
    expect(await screen.findByDisplayValue("Đã lưu hành động")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Bản nháp")).toBeInTheDocument();
  });

  it("offers an explicit economy retry for an asynchronously failed quota job", async () => {
    localStorage.clear();
    localStorage.setItem(generationIdentityKey("owner-1", "campaign-1", "branch-1"), JSON.stringify({ ownerId: "owner-1", campaignId: "campaign-1", branchId: "branch-1", checkpointId: "checkpoint-1", action: "Giữ hành động", previewId: "preview-1", idempotencyKey: "key-1", jobId: "job-5" }));
    const response = () => new Response(JSON.stringify({ id: "job-5", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "failed", action: "Giữ hành động", draft: "", offset: 0, offset_unit: "utf16_code_units", failure: { code: "UNSUPPORTED_CAPABILITY", message: "native capability unavailable" } }));
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(response()));
    vi.stubGlobal("fetch", fetchMock);
    render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={vi.fn()} />);
    expect(await screen.findByRole("button", { name: "Thử economy miễn phí" })).toBeInTheDocument();
    expect(screen.getByDisplayValue("Giữ hành động")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const user = userEvent.setup(); await user.click(screen.getByRole("button", { name: "Thử economy miễn phí" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    const generateCall = fetchMock.mock.calls[2]; const payload = JSON.parse(String(generateCall[1]?.body));
    expect(payload.mode).toBe("economy"); expect(payload.policy).toBe("free_only"); expect(payload.cap).toBeNull();
    expect(payload.idempotency_key).not.toBe("key-1");
  });

  it("uses the pinned context role and paid cap for quality generation", async () => {
    localStorage.clear(); let generatePayload: Record<string, unknown> | undefined;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ settings_revision: 2, mode: "quality", policy: "capped_paid", confirmed_usd_cap: "1.25", roles: { context: { id: "context-profile", version: 4 } }, budgets: {} })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "preview-quality", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "quality-head", action: "Đi sâu", status: "ready", profile_id: "context-profile" }), { status: 201 }))
      .mockImplementationOnce((_input, init) => { generatePayload = JSON.parse(String(init?.body)); return Promise.resolve(new Response(JSON.stringify({ id: "job-quality", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "quality-head", status: "queued", draft: "", offset: 0, offset_unit: "utf16_code_units" }))); });
    vi.stubGlobal("fetch", fetchMock); const user = userEvent.setup();
    render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="" onCommitted={vi.fn()} />);
    await user.type(screen.getByLabelText("Hành động tiếp theo"), "Đi sâu"); await user.click(screen.getByRole("button", { name: "Kể tiếp" }));
    await waitFor(() => expect(generatePayload).toMatchObject({ checkpoint_id: "quality-head", mode: "quality", policy: "capped_paid", cap: "1.25" }));
  });

  it("blocks quality setup when the context role is missing", async () => {
    localStorage.clear();
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ settings_revision: 2, mode: "quality", policy: "capped_paid", confirmed_usd_cap: "1.25", roles: {}, budgets: {} })));
    vi.stubGlobal("fetch", fetchMock); const user = userEvent.setup();
    render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="" onCommitted={vi.fn()} />);
    await user.type(screen.getByLabelText("Hành động tiếp theo"), "Thiếu vai trò"); await user.click(screen.getByRole("button", { name: "Kể tiếp" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Chưa cấu hình hồ sơ nhà cung cấp");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("blocks a new send while an owned active job is recoverable", async () => {
    localStorage.clear();
    const projected: CampaignProjection = { ...projection, jobs: [{ id: "job-6", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "running", mode: "economy", action: "Đang chạy", created_at: "", cancel_requested: false }] };
    const fetchMock = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ id: "job-6", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "running", action: "Đang chạy", draft: "", offset: 0, offset_unit: "utf16_code_units" }))).mockResolvedValueOnce(new Response(JSON.stringify({ events: [] })));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<GenerationComposer ownerId="owner-1" projection={projected} profileId="profile-1" onCommitted={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Giai đoạn: running")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Kể tiếp" }));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("selects the configured narrator provider role for an economy preview", async () => {
    localStorage.clear();
    let generatePayload: Record<string, unknown> | undefined;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ settings_revision: 1, mode: "economy", policy: "free_only", confirmed_usd_cap: null, roles: { narrator: { id: "narrator-profile", version: 2 } }, budgets: {} })))
      .mockImplementationOnce((_input, init) => { const payload = JSON.parse(String(init?.body)); expect(payload.profile_id).toBe("narrator-profile"); return Promise.resolve(new Response(JSON.stringify({ id: "preview-role", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-current", action: "Đi tiếp", status: "ready", profile_id: "narrator-profile" }), { status: 201 })); })
      .mockImplementationOnce((_input, init) => { generatePayload = JSON.parse(String(init?.body)); return Promise.resolve(new Response(JSON.stringify({ id: "job-role", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-current", status: "queued", draft: "", offset: 0, offset_unit: "utf16_code_units" }))); });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="" onCommitted={vi.fn()} />);
    await user.type(screen.getByLabelText("Hành động tiếp theo"), "Đi tiếp");
    await user.click(screen.getByRole("button", { name: "Kể tiếp" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(generatePayload).toMatchObject({ checkpoint_id: "checkpoint-current", mode: "economy", policy: "free_only", cap: null });
    expect(JSON.parse(localStorage.getItem(generationIdentityKey("owner-1", "campaign-1", "branch-1"))!).checkpointId).toBe("checkpoint-current");
  });

  it("keeps an unresolved idempotency key from creating a replacement generation", async () => {
    localStorage.clear();
    localStorage.setItem(generationIdentityKey("owner-1", "campaign-1", "branch-1"), JSON.stringify({ ownerId: "owner-1", campaignId: "campaign-1", branchId: "branch-1", checkpointId: "checkpoint-1", action: "Chờ khôi phục", previewId: "preview-1", idempotencyKey: "same-key" }));
    const fetchMock = vi.fn().mockResolvedValue(new Response("missing", { status: 404, headers: { "content-type": "text/plain" } }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Kể tiếp" }));
    expect(fetchMock).toHaveBeenCalledWith("/api/generation/jobs/by-key?branch_id=branch-1&idempotency_key=same-key", expect.anything());
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  });

  it("replaces a delta gap with authoritative content and supports cancel and draft PUT", async () => {
    localStorage.clear();
    localStorage.setItem(generationIdentityKey("owner-1", "campaign-1", "branch-1"), JSON.stringify({ ownerId: "owner-1", campaignId: "campaign-1", branchId: "branch-1", checkpointId: "checkpoint-1", action: "Giữ", previewId: "preview-1", idempotencyKey: "key-1", jobId: "job-7" }));
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "job-7", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "running", draft: "A", offset: 1, offset_unit: "utf16_code_units" })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ events: [{ id: 4, stage: "narration", event_type: "narration_delta", offset: 4, content: "x" }] })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "job-7", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "running", draft: "Server authoritative", offset: 19, offset_unit: "utf16_code_units" })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "job-7", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "running", draft: "Đã sửa", offset: 7, offset_unit: "utf16_code_units" })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "job-7", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "cancelled", draft: "Đã sửa", offset: 7, offset_unit: "utf16_code_units" })));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={vi.fn()} />);
    expect(await screen.findByDisplayValue("Server authoritative")).toBeInTheDocument();
    const draftField = screen.getByLabelText("Bản nháp kể chuyện");
    await user.clear(draftField); await user.type(draftField, "Đã sửa"); await user.click(screen.getByRole("button", { name: "Lưu bản nháp" }));
    await user.click(screen.getByRole("button", { name: "Hủy" }));
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PUT" && String(init.body).includes("Đã sửa"))).toBe(true);
    expect(await screen.findByText("Giai đoạn: cancelled")).toBeInTheDocument();
  });

  it("keeps a candidate immutable and suppresses IME composition submit", async () => {
    localStorage.clear();
    localStorage.setItem(generationIdentityKey("owner-1", "campaign-1", "branch-1"), JSON.stringify({ ownerId: "owner-1", campaignId: "campaign-1", branchId: "branch-1", checkpointId: "checkpoint-1", action: "Ứng viên", previewId: "preview-1", idempotencyKey: "key-1", jobId: "job-8" }));
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: "job-8", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "candidate", draft: "Hoàn chỉnh", offset: 10, offset_unit: "utf16_code_units" })));
    vi.stubGlobal("fetch", fetchMock);
    render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={vi.fn()} />);
    await screen.findByText("Giai đoạn: candidate");
    expect(screen.getByLabelText("Bản nháp kể chuyện")).toHaveAttribute("readonly");
    expect(screen.getByRole("button", { name: "Lưu bản nháp" })).toBeDisabled();
    const actionField = screen.getByLabelText("Hành động tiếp theo");
    fireEvent.keyDown(actionField, { key: "Enter", isComposing: true, keyCode: 229 });
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  });

  it("does not overwrite an unsaved draft while polling the same server draft", async () => {
    localStorage.clear();
    localStorage.setItem(generationIdentityKey("owner-1", "campaign-1", "branch-1"), JSON.stringify({ ownerId: "owner-1", campaignId: "campaign-1", branchId: "branch-1", checkpointId: "checkpoint-1", action: "Giữ", previewId: "preview-1", idempotencyKey: "key-1", jobId: "job-9" }));
    const job = () => new Response(JSON.stringify({ id: "job-9", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "running", draft: "Server draft", offset: 12, offset_unit: "utf16_code_units" }));
    let calls = 0;
    const fetchMock = vi.fn().mockImplementation(() => { const response = calls++ % 2 === 0 ? job() : new Response(JSON.stringify({ events: [] })); return Promise.resolve(response); });
    vi.stubGlobal("fetch", fetchMock);
    render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={vi.fn()} />);
    await waitFor(() => expect(screen.getByDisplayValue("Server draft")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Bản nháp kể chuyện"), { target: { value: "Local unsaved draft" } });
    await new Promise((resolve) => setTimeout(resolve, 1400));
    await waitFor(() => expect(screen.getByDisplayValue("Local unsaved draft")).toBeInTheDocument());
  });

  it("allows a new action after directly committing a recovered candidate", async () => {
    localStorage.clear();
    localStorage.setItem(generationIdentityKey("owner-1", "campaign-1", "branch-1"), JSON.stringify({ ownerId: "owner-1", campaignId: "campaign-1", branchId: "branch-1", checkpointId: "checkpoint-1", action: "Ứng viên cũ", previewId: "preview-old", idempotencyKey: "key-old", jobId: "job-10" }));
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "job-10", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "candidate", action: "Ứng viên cũ", draft: "Kết quả", offset: 7, offset_unit: "utf16_code_units" })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "preview-new", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-new", action: "Hành động mới", status: "ready", profile_id: "profile-1" }), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "job-new", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-new", status: "queued", draft: "", offset: 0, offset_unit: "utf16_code_units" })));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={vi.fn().mockResolvedValue(projection)} />);
    await screen.findByText("Giai đoạn: candidate");
    await user.click(screen.getByRole("button", { name: "Commit ứng viên" }));
    const actionField = screen.getByLabelText("Hành động tiếp theo"); await user.clear(actionField); await user.type(actionField, "Hành động mới");
    await user.click(screen.getByRole("button", { name: "Kể tiếp" }));
    await waitFor(() => expect(screen.getByText("Giai đoạn: queued")).toBeInTheDocument());
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/context/previews"))).toBe(true);
  });

  it("shows authoritative candidate text after a dirty running draft becomes immutable", async () => {
    localStorage.clear();
    localStorage.setItem(generationIdentityKey("owner-1", "campaign-1", "branch-1"), JSON.stringify({ ownerId: "owner-1", campaignId: "campaign-1", branchId: "branch-1", checkpointId: "checkpoint-1", action: "Đang chạy", previewId: "preview-1", idempotencyKey: "key-1", jobId: "job-11" }));
    const running = () => new Response(JSON.stringify({ id: "job-11", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "running", action: "Đang chạy", draft: "Server draft", offset: 12, offset_unit: "utf16_code_units" }));
    const candidate = () => new Response(JSON.stringify({ id: "job-11", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "candidate", action: "Đang chạy", draft: "Authoritative candidate", offset: 22, offset_unit: "utf16_code_units" }));
    let calls = 0; const fetchMock = vi.fn().mockImplementation(() => { const index = calls++; const response = index === 0 ? running() : index === 2 ? candidate() : new Response(JSON.stringify({ events: [] })); return Promise.resolve(response); });
    vi.stubGlobal("fetch", fetchMock); render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={vi.fn()} />);
    await waitFor(() => expect(screen.getByDisplayValue("Server draft")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Bản nháp kể chuyện"), { target: { value: "Local draft" } });
    await new Promise((resolve) => setTimeout(resolve, 1400));
    expect(screen.getByDisplayValue("Authoritative candidate")).toBeInTheDocument();
  });
});
