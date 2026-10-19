import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { GenerationComposer, mergeGenerationEvents, generationIdentityKey } from "./GenerationComposer";
import type { CampaignProjection } from "../api/types";

const projection = { campaign: { id: "campaign-1", title: "Test", created_at: "", updated_at: "", archived_at: null }, branch: { id: "branch-1", name: "main", state_version: 3, checkpoint_id: "checkpoint-1" }, checkpoint: { id: "checkpoint-1", state_version: 3, parent_checkpoint_id: null, selected_revision_ids: [], retrieval_policy: "auto" }, profiles: {}, scene: null, transcript: [], jobs: [] } as CampaignProjection;

describe("GenerationComposer", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });
  it("explains synthetic demo behavior when demo mode is enabled", () => {
    render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={vi.fn()} demoMode />);
    const notice = screen.getByRole("status", { name: "Chế độ demo tổng hợp" });
    expect(notice).toHaveClass("composer-runtime-notice");
    expect(notice).toHaveTextContent("Phản hồi mẫu có thể lặp lại");
    expect(notice).toHaveTextContent("Đổi model không gọi AI thật");
    expect(notice).not.toHaveTextContent("Cài đặt");
  });

  it("does not show synthetic demo messaging by default", () => {
    render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={vi.fn()} />);
    expect(screen.queryByRole("status", { name: "Chế độ demo tổng hợp" })).not.toBeInTheDocument();
  });
  it("submits with Enter, keeps Shift+Enter as a newline, and ignores IME Enter", async () => {
    localStorage.clear();
    const preview = { id: "preview-enter", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", action: "Xin chào\n", status: "ready", profile_id: "profile-1" };
    const queued = { id: "job-enter", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "queued", draft: "", offset: 0, offset_unit: "utf16_code_units" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(preview), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(queued), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={vi.fn()} />);
    const input = screen.getByLabelText("Hành động tiếp theo");
    await user.type(input, "Xin chào");
    await user.keyboard("{Shift>}{Enter}{/Shift}");
    expect(input).toHaveValue("Xin chào\n");
    expect(fetchMock).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: "Enter", keyCode: 229, isComposing: true });
    expect(fetchMock).not.toHaveBeenCalled();
    await user.keyboard("{Enter}");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

  it("shows one Send action and no candidate action buttons", () => {
    render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Gửi" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: /Hủy|Lưu bản nháp|Commit|economy/i })).not.toBeInTheDocument();
  });

  it("automatically commits a recovered candidate and refreshes the story", async () => {
    localStorage.clear();
    localStorage.setItem(generationIdentityKey("owner-1", "campaign-1", "branch-1"), JSON.stringify({ ownerId: "owner-1", campaignId: "campaign-1", branchId: "branch-1", checkpointId: "checkpoint-1", action: "Ứng viên cũ", previewId: "preview-old", idempotencyKey: "key-old", jobId: "job-10" }));
    const candidate = { id: "job-10", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "candidate", action: "Ứng viên cũ", draft: "Kết quả", offset: 7, offset_unit: "utf16_code_units" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(candidate)))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true })));
    vi.stubGlobal("fetch", fetchMock);
    const onCommitted = vi.fn().mockResolvedValue(projection);
    render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={onCommitted} />);
    await waitFor(() => expect(onCommitted).toHaveBeenCalledOnce());
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(localStorage.getItem(generationIdentityKey("owner-1", "campaign-1", "branch-1"))).toBeNull();
  });

  it("refreshes a recovered committed job only once under StrictMode", async () => {
    localStorage.setItem(generationIdentityKey("owner-1", "campaign-1", "branch-1"), JSON.stringify({ ownerId: "owner-1", campaignId: "campaign-1", branchId: "branch-1", checkpointId: "checkpoint-1", action: "ÄÃ£ xong", previewId: "preview-old", idempotencyKey: "key-old", jobId: "job-committed" }));
    const committed = { id: "job-committed", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "committed", draft: "", offset: 0, offset_unit: "utf16_code_units" };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(committed))));
    const onCommitted = vi.fn().mockResolvedValue(projection);
    render(<StrictMode><GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={onCommitted} /></StrictMode>);
    await waitFor(() => expect(onCommitted).toHaveBeenCalledTimes(1));
  });

  it("preserves a new action typed while an old candidate is committing", async () => {
    localStorage.setItem(generationIdentityKey("owner-1", "campaign-1", "branch-1"), JSON.stringify({ ownerId: "owner-1", campaignId: "campaign-1", branchId: "branch-1", checkpointId: "checkpoint-1", action: "Lượt cũ", previewId: "preview-old", idempotencyKey: "key-old", jobId: "job-candidate" }));
    const candidate = { id: "job-candidate", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "candidate", action: "Lượt cũ", draft: "Kết quả", offset: 7, offset_unit: "utf16_code_units" };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(candidate))).mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }))));
    let resolveRefresh: (value: CampaignProjection) => void = () => undefined;
    const onCommitted = vi.fn().mockReturnValue(new Promise<CampaignProjection>((resolve) => { resolveRefresh = resolve; }));
    render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={onCommitted} />);
    const actionField = await screen.findByLabelText("Hành động tiếp theo");
    await waitFor(() => expect(actionField).toHaveValue("Lượt cũ"));
    await userEvent.setup().clear(actionField);
    await userEvent.setup().type(actionField, "Lượt cũ");
    await waitFor(() => expect(onCommitted).toHaveBeenCalledTimes(1));
    await act(async () => { resolveRefresh(projection); });
    await waitFor(() => expect(screen.getByRole("button", { name: "Gửi" })).toBeEnabled());
    expect(actionField).toHaveValue("Lượt cũ");
  });

  it("does not commit the same candidate again after delayed recovery", async () => {
    localStorage.setItem(generationIdentityKey("owner-1", "campaign-1", "branch-1"), JSON.stringify({ ownerId: "owner-1", campaignId: "campaign-1", branchId: "branch-1", checkpointId: "checkpoint-1", action: "Ứng viên", previewId: "preview-1", idempotencyKey: "key-1", jobId: "job-repeat" }));
    const candidate = { id: "job-repeat", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "candidate", action: "Ứng viên", draft: "Kết quả", offset: 7, offset_unit: "utf16_code_units" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(candidate)))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true })))
      .mockResolvedValueOnce(new Response(JSON.stringify(candidate)));
    vi.stubGlobal("fetch", fetchMock);
    const onCommitted = vi.fn().mockResolvedValue(projection);
    const { rerender } = render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={onCommitted} />);
    await waitFor(() => expect(onCommitted).toHaveBeenCalledOnce());
    const branch2 = { ...projection, branch: { ...projection.branch, id: "branch-2" } };
    localStorage.setItem(generationIdentityKey("owner-1", "campaign-1", "branch-2"), JSON.stringify({ ownerId: "owner-1", campaignId: "campaign-1", branchId: "branch-2", checkpointId: "checkpoint-1", action: "Ứng viên", previewId: "preview-1", idempotencyKey: "key-1", jobId: "job-repeat" }));
    rerender(<GenerationComposer ownerId="owner-1" projection={branch2} profileId="profile-1" onCommitted={onCommitted} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/commit")).length).toBe(1);
  });


  it("recovers a definitive 422 rejection so a deliberate second Send gets a new key", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "preview-rejected", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", action: "Chào", status: "ready", profile_id: "profile-1" }), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Invalid request" }), { status: 422 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "preview-retry", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", action: "Chào", status: "ready", profile_id: "profile-1" }), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "job-retry", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "queued", draft: "", offset: 0, offset_unit: "utf16_code_units" }), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={vi.fn()} />);
    const input = screen.getByLabelText("Hành động tiếp theo");
    await user.type(input, "Chào");
    await user.click(screen.getByRole("button", { name: "Gửi" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(input).toHaveValue("Chào");
    expect(localStorage.getItem(generationIdentityKey("owner-1", "campaign-1", "branch-1"))).toBeNull();
    await user.click(screen.getByRole("button", { name: "Gửi" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
    const rejectedBody = JSON.parse(String(fetchMock.mock.calls[1][1]?.body));
    const retryBody = JSON.parse(String(fetchMock.mock.calls[3][1]?.body));
    expect(retryBody.idempotency_key).not.toBe(rejectedBody.idempotency_key);
    expect(retryBody.preview_id).toBe("preview-retry");
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/generate"))).toHaveLength(2);
  });

  it("refreshes authoritative state after a rejected stale 409 before a new deliberate Send", async () => {
    const advanced = { ...projection, branch: { ...projection.branch, state_version: 4, checkpoint_id: "checkpoint-2" }, checkpoint: { ...projection.checkpoint, id: "checkpoint-2", state_version: 4 } };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "preview-stale", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", action: "Đi tiếp", status: "ready", profile_id: "profile-1" }), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Generation checkpoint is stale" }), { status: 409 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Generation job not found" }), { status: 404 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "preview-fresh", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-2", action: "Đi tiếp", status: "ready", profile_id: "profile-1" }), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "job-fresh", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-2", status: "queued", draft: "", offset: 0, offset_unit: "utf16_code_units" }), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    const onCommitted = vi.fn().mockResolvedValue(advanced);
    const user = userEvent.setup();
    const { rerender } = render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={onCommitted} />);
    await user.type(screen.getByLabelText("Hành động tiếp theo"), "Đi tiếp");
    await user.click(screen.getByRole("button", { name: "Gửi" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    await waitFor(() => expect(onCommitted).toHaveBeenCalledOnce());
    expect(localStorage.getItem(generationIdentityKey("owner-1", "campaign-1", "branch-1"))).toBeNull();
    rerender(<GenerationComposer ownerId="owner-1" projection={advanced} profileId="profile-1" onCommitted={onCommitted} />);
    await user.click(screen.getByRole("button", { name: "Gửi" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(5));
    const secondBody = JSON.parse(String(fetchMock.mock.calls[4][1]?.body));
    expect(secondBody.checkpoint_id).toBe("checkpoint-2");
    expect(secondBody.preview_id).toBe("preview-fresh");
  });


  it("does not adopt or commit a conflicting existing job after 409", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "preview-collision", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", action: "Đúng", status: "ready", profile_id: "profile-1" }), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Conflicting idempotency payload" }), { status: 409 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "job-foreign", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", action: "Khác", status: "candidate", draft: "Foreign", offset: 7, offset_unit: "utf16_code_units" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={vi.fn()} />);
    await user.type(screen.getByLabelText("Hành động tiếp theo"), "Đúng");
    await user.click(screen.getByRole("button", { name: "Gửi" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(localStorage.getItem(generationIdentityKey("owner-1", "campaign-1", "branch-1"))).toContain("preview-collision");
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/commit"))).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "Gửi" }));
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("does not create a new generation after an ambiguous 503 and a failed by-key recovery", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "preview-ambiguous", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", action: "Tiếp", status: "ready", profile_id: "profile-1" }), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "quota schema unavailable" }), { status: 503 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Lookup unavailable" }), { status: 503 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={vi.fn()} />);
    await user.type(screen.getByLabelText("Hành động tiếp theo"), "Tiếp");
    await user.click(screen.getByRole("button", { name: "Gửi" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    const saved = localStorage.getItem(generationIdentityKey("owner-1", "campaign-1", "branch-1"));
    expect(saved).toContain("preview-ambiguous");
    await user.click(screen.getByRole("button", { name: "Gửi" }));
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(localStorage.getItem(generationIdentityKey("owner-1", "campaign-1", "branch-1"))).toBe(saved);
  });

  it("retains a committed candidate until the parent confirms its refreshed projection", async () => {
    const candidate = { id: "job-committed-refresh", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "candidate", action: "Chào", draft: "Mira đáp lời", offset: 12, offset_unit: "utf16_code_units" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "preview-commit", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", action: "Chào", status: "ready", profile_id: "profile-1" }), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(candidate), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true })));
    vi.stubGlobal("fetch", fetchMock);
    const onCommitted = vi.fn().mockResolvedValueOnce(undefined).mockResolvedValueOnce(projection);
    const user = userEvent.setup();
    render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={onCommitted} />);
    await user.type(screen.getByLabelText("Hành động tiếp theo"), "Chào");
    await user.click(screen.getByRole("button", { name: "Gửi" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    const saved = localStorage.getItem(generationIdentityKey("owner-1", "campaign-1", "branch-1"));
    expect(saved).toContain("job-committed-refresh");
    expect(screen.getByLabelText("Hành động tiếp theo")).toHaveValue("Chào");
    await user.click(screen.getByRole("button", { name: "Gửi" }));
    await waitFor(() => expect(onCommitted).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(localStorage.getItem(generationIdentityKey("owner-1", "campaign-1", "branch-1"))).toBeNull());
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/generate"))).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/commit"))).toHaveLength(2);
  });

  it("keeps the player input and re-enables Send when generation fails", async () => {
    localStorage.clear();
    const preview = { id: "preview-error", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", action: "Xin chào", status: "ready", profile_id: "profile-1" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(preview), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ message: "provider unavailable" }), { status: 503 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={vi.fn()} />);
    const input = screen.getByLabelText("Hành động tiếp theo");
    await user.type(input, "Xin chào");
    await user.click(screen.getByRole("button", { name: "Gửi" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(input).toHaveValue("Xin chào");
    expect(screen.getByRole("button", { name: "Gửi" })).toBeEnabled();
  });

  it("commits a direct candidate response without starting another generation", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "preview-direct", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", action: "Đi tiếp", status: "ready", profile_id: "profile-1" }), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "job-direct", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "candidate", action: "Đi tiếp", draft: "Kết quả", offset: 7, offset_unit: "utf16_code_units" })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true })));
    vi.stubGlobal("fetch", fetchMock);
    const onCommitted = vi.fn().mockResolvedValue(projection);
    const user = userEvent.setup();
    render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={onCommitted} />);
    await user.type(screen.getByLabelText("Hành động tiếp theo"), "Đi tiếp");
    await user.click(screen.getByRole("button", { name: "Gửi" }));
    await waitFor(() => expect(onCommitted).toHaveBeenCalledOnce());
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/context/previews"))).toBe(true);
  });

  it("keeps Send in progress while recovered candidate commit refresh is in flight", async () => {
    let releaseRefresh!: () => void;
    const refresh = new Promise<CampaignProjection>((resolve) => { releaseRefresh = () => resolve(projection); });
    localStorage.setItem(generationIdentityKey("owner-1", "campaign-1", "branch-1"), JSON.stringify({ ownerId: "owner-1", campaignId: "campaign-1", branchId: "branch-1", checkpointId: "checkpoint-1", action: "Ứng viên", previewId: "preview-1", idempotencyKey: "key-1", jobId: "job-inflight" }));
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "job-inflight", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "candidate", action: "Ứng viên", draft: "Kết quả", offset: 7, offset_unit: "utf16_code_units" })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true })));
    vi.stubGlobal("fetch", fetchMock);
    const onCommitted = vi.fn().mockReturnValue(refresh);
    render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={onCommitted} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("button", { name: "Đang gửi…" })).toBeDisabled();
    releaseRefresh();
    await waitFor(() => expect(screen.queryByRole("button", { name: "Đang gửi…" })).not.toBeInTheDocument());
  });

  it("retries a definitive quota failure through a fresh economy send", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "preview-paid", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", action: "Xin chào", status: "ready", profile_id: "profile-1" }), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ message: "quota exceeded", code: "QUOTA_EXCEEDED" }), { status: 429 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "preview-free", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", action: "Xin chào", status: "ready", profile_id: "profile-1" }), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "job-free", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "queued", draft: "", offset: 0, offset_unit: "utf16_code_units" })));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={vi.fn()} />);
    await user.type(screen.getByLabelText("Hành động tiếp theo"), "Xin chào");
    await user.click(screen.getByRole("button", { name: "Gửi" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Chỉ model được xác minh Free mới được gửi");
    await user.click(screen.getByRole("button", { name: "Gửi" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
    expect(JSON.parse(String(fetchMock.mock.calls[3][1]?.body))).toMatchObject({ mode: "economy", policy: "free_only", cap: null });
  });

  it("uses one plain chat composer with an action syntax hint and no category starters", () => {
    render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={vi.fn()} />);
    expect(document.querySelector(".composer-starters")).toBeNull();
    expect(screen.getByText("Dùng **...** cho hành động hoặc suy nghĩ; văn bản thường là lời thoại.")).toBeInTheDocument();
  });

  it("keeps the composer as one editable textbox", () => {
    render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={vi.fn()} />);
    expect(screen.getByLabelText("Hành động tiếp theo")).toHaveValue("");
    expect(screen.getAllByRole("button", { name: "Gửi" })).toHaveLength(1);
  });

  it("does not expose category quick insert buttons", () => {
    render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Suy nghĩ" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Bối cảnh" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Hành động" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Lời thoại" })).not.toBeInTheDocument();
  });

  it("accepts ordinary dialogue and action markup in the same textbox", async () => {
    const user = userEvent.setup();
    render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={vi.fn()} />);
    const actionField = screen.getByLabelText("Hành động tiếp theo");
    await user.type(actionField, "Xin chào **vẫy tay**");
    expect(actionField).toHaveValue("Xin chào **vẫy tay**");
  });

  it("preserves leading and trailing action whitespace when sending", async () => {
    localStorage.clear();
    let previewPayload: Record<string, unknown> | undefined;
    const fetchMock = vi.fn()
      .mockImplementationOnce((_input, init) => { previewPayload = JSON.parse(String(init?.body)); return Promise.resolve(new Response(JSON.stringify({ id: "preview-space", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", action: previewPayload?.action, status: "ready", profile_id: "profile-1" }), { status: 201 })); })
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "job-space", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "queued", draft: "", offset: 0, offset_unit: "utf16_code_units" })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "job-space", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "queued", draft: "", offset: 0, offset_unit: "utf16_code_units" })));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={vi.fn()} />);
    await user.type(screen.getByLabelText("Hành động tiếp theo"), "  Xin chào  ");
    await user.click(screen.getByRole("button", { name: "Gửi" }));
    await waitFor(() => expect(previewPayload?.action).toBe("  Xin chào  "));
    localStorage.clear();
  });

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
    await user.click(screen.getByRole("button", { name: "Gửi" }));
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
    expect(screen.getByRole("button", { name: "Đang gửi…" })).toBeDisabled();
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
    const fetchMock = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ id: "job-3", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "candidate", draft: "Kết quả", offset: 7, offset_unit: "utf16_code_units" }))).mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }))).mockResolvedValueOnce(new Response(JSON.stringify({ ok: true })));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const onCommitted = vi.fn().mockRejectedValueOnce(new Error("refresh unavailable")).mockResolvedValue(projection);
    render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={onCommitted} />);
    const actionField = await screen.findByLabelText("Hành động tiếp theo");
    await user.clear(actionField);
    await user.type(actionField, "Mới");
    await user.click(screen.getByRole("button", { name: "Gửi" }));
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/context/previews"))).toBe(false);
    expect(screen.queryByText("Giai đoạn: queued")).not.toBeInTheDocument();
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
    expect(await screen.findByRole("button", { name: "Gửi" })).toBeInTheDocument();
    expect(screen.getByDisplayValue("Giữ hành động")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const user = userEvent.setup(); await user.click(screen.getByRole("button", { name: "Gửi" }));
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
    await user.type(screen.getByLabelText("Hành động tiếp theo"), "Đi sâu"); await user.click(screen.getByRole("button", { name: "Gửi" }));
    await waitFor(() => expect(generatePayload).toMatchObject({ checkpoint_id: "quality-head", mode: "quality", policy: "capped_paid", cap: "1.25" }));
  });

  it("blocks quality setup when the context role is missing", async () => {
    localStorage.clear();
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ settings_revision: 2, mode: "quality", policy: "capped_paid", confirmed_usd_cap: "1.25", roles: {}, budgets: {} })));
    vi.stubGlobal("fetch", fetchMock); const user = userEvent.setup();
    render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="" onCommitted={vi.fn()} />);
    await user.type(screen.getByLabelText("Hành động tiếp theo"), "Thiếu vai trò"); await user.click(screen.getByRole("button", { name: "Gửi" }));
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
    expect(screen.getByRole("button", { name: "Đang gửi…" })).toBeDisabled();
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
    await user.click(screen.getByRole("button", { name: "Gửi" }));
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
    await user.click(screen.getByRole("button", { name: "Gửi" }));
    expect(fetchMock).toHaveBeenCalledWith("/api/generation/jobs/by-key?branch_id=branch-1&idempotency_key=same-key", expect.anything());
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  });

  it("replaces a delta gap with authoritative content", async () => {
    localStorage.clear();
    localStorage.setItem(generationIdentityKey("owner-1", "campaign-1", "branch-1"), JSON.stringify({ ownerId: "owner-1", campaignId: "campaign-1", branchId: "branch-1", checkpointId: "checkpoint-1", action: "Giữ", previewId: "preview-1", idempotencyKey: "key-1", jobId: "job-7" }));
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "job-7", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "running", draft: "A", offset: 1, offset_unit: "utf16_code_units" })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ events: [{ id: 4, stage: "narration", event_type: "narration_delta", offset: 4, content: "x" }] })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "job-7", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "running", draft: "Server authoritative", offset: 19, offset_unit: "utf16_code_units" })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "job-7", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "running", draft: "Server authoritative", offset: 19, offset_unit: "utf16_code_units" })));
    vi.stubGlobal("fetch", fetchMock);
    render(<GenerationComposer ownerId="owner-1" projection={projection} profileId="profile-1" onCommitted={vi.fn()} />);
    expect(await screen.findByDisplayValue("Server authoritative")).toBeInTheDocument();
  });

  it.skip("keeps a candidate immutable and suppresses IME composition submit", async () => {
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

  it.skip("does not overwrite an unsaved draft while polling the same server draft", async () => {
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

  it("allows a new action after automatically committing a recovered candidate", async () => {
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
    const actionField = await screen.findByLabelText("Hành động tiếp theo");
    await waitFor(() => expect(actionField).toHaveValue(""));
    await user.type(actionField, "Hành động mới");
    await user.click(screen.getByRole("button", { name: "Gửi" }));
    await waitFor(() => expect(screen.getByText("Giai đoạn: queued")).toBeInTheDocument());
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/context/previews"))).toBe(true);
  });

  it.skip("shows authoritative candidate text after a dirty running draft becomes immutable", async () => {
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
