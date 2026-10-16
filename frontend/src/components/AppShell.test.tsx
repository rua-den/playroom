import { afterEach, describe, expect, it, vi } from "vitest";
import { StrictMode } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { recoverableJobCount, recoverableJobSummary } from "./AppShell";
import { AppShell, ImportReviewPanel } from "./AppShell";
import { api } from "../api/client";

vi.mock("./GenerationComposer", () => ({ GenerationComposer: () => <div data-testid="generation-composer" /> }));
vi.mock("./ProfileEditor", () => ({ ProfileEditor: () => <div data-testid="profile-editor" /> }));
vi.mock("./MemoryLibrary", () => ({ MemoryLibrary: () => <div data-testid="memory-library" /> }));
vi.mock("./SceneEditor", () => ({ SceneEditor: () => <div data-testid="scene-editor" /> }));
vi.mock("./SettingsPanel", () => ({ SettingsPanel: () => <div data-testid="settings-panel" /> }));

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("recoverable job summary", () => {
  function reviewProjection(checkpoint = "checkpoint", campaign = "imported") {
    return { campaign: { id: campaign, title: campaign, created_at: "2026-01-01", updated_at: "2026-01-01", archived_at: null }, branch: { id: "branch", name: "main", state_version: 1, checkpoint_id: checkpoint }, checkpoint: { id: checkpoint, state_version: 1, parent_checkpoint_id: null, selected_revision_ids: [], retrieval_policy: "auto" as const }, profiles: {}, scene: null, transcript: [], jobs: [], import_review: { required: true, approved: false, review: {} } };
  }

  function mockReviewSnapshot() {
    vi.spyOn(api, "listMemory").mockResolvedValue([]);
    vi.spyOn(api, "getScene").mockResolvedValue({ focus_scene_id: null, scenes: {} });
  }

  it("renders structured player turns and attributed NPC dialogue", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: "campaign-structured", title: "Structured", created_at: "2026-01-01", updated_at: "2026-01-01", archived_at: null }]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "campaign-structured", title: "Structured", created_at: "2026-01-01", updated_at: "2026-01-01", archived_at: null, branch_id: "branch-structured", state_version: 1, checkpoint_id: "checkpoint-structured", profiles: {} }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ campaign: { id: "campaign-structured", title: "Structured", created_at: "2026-01-01", updated_at: "2026-01-01", archived_at: null }, branch: { id: "branch-structured", name: "main", state_version: 1, checkpoint_id: "checkpoint-structured" }, checkpoint: { id: "checkpoint-structured", state_version: 1, parent_checkpoint_id: null, selected_revision_ids: [], retrieval_policy: "auto" }, profiles: { "character:npc-structured": { kind: "character", version: 1, data: { name: "Mira" } } }, scene: null, transcript: [{ revision_id: "revision-structured", turn_id: "turn-structured", sequence: 1, action_text: "legacy raw", revision: 1, narrative_text: "legacy fallback", input_segments: [{ kind: "dialogue", text: "Hello" }, { kind: "action", text: "waves" }], output_segments: [{ kind: "narration", text: "# Chương I\n\n*Đêm xuống.*", profile_version_id: "profile-structured" }, { kind: "dialogue", text: "Welcome.", character_id: "npc-structured", profile_version_id: "profile-structured" }], complete: true, selected: true }], jobs: [] }), { status: 200 })));
    render(<AppShell owner={{ id: "owner-structured", email: "owner@example.test" }} onLogout={() => undefined} />);
    expect(await screen.findByText("Hello")).toBeInTheDocument();
    expect(await screen.findByText("waves")).toBeInTheDocument();
    expect(await screen.findByText("Welcome.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Chương I" })).toBeInTheDocument();
    expect(screen.getByText("Đêm xuống.").tagName).toBe("EM");
    expect(screen.getByText("Mira:")).toBeInTheDocument();
    expect(screen.queryByText("legacy raw")).not.toBeInTheDocument();
  });

  it("counts only jobs that can still be recovered", () => {
    const jobs = ["queued", "running", "cancelling", "interrupted", "candidate", "committed", "failed", "cancelled"];
    expect(recoverableJobCount(jobs.map((status) => ({ status })))).toBe(5);
  });

  it("makes the recent jobs query cap explicit in the summary", () => {
    expect(recoverableJobSummary(3)).toBe("Có thể khôi phục trong danh sách (tối đa 20 việc): 3");
  });

  it("keeps the conversation central with topbar controls and an on-demand context panel", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: "campaign-1", title: "Mùa hạ", created_at: "2026-01-01", updated_at: "2026-01-01", archived_at: null }]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "campaign-1", title: "Mùa hạ", created_at: "2026-01-01", updated_at: "2026-01-01", archived_at: null, branch_id: "branch-1", state_version: 1, checkpoint_id: "checkpoint-1", profiles: {} }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ campaign: { id: "campaign-1", title: "Mùa hạ", created_at: "2026-01-01", updated_at: "2026-01-01", archived_at: null }, branch: { id: "branch-1", name: "Chính", state_version: 1, checkpoint_id: "checkpoint-1" }, checkpoint: { id: "checkpoint-1", state_version: 1, parent_checkpoint_id: null, selected_revision_ids: [], retrieval_policy: "auto" }, profiles: {}, scene: null, transcript: [{ revision_id: "revision-1", turn_id: "turn-1", sequence: 1, action_text: "Bước vào vườn", revision: 1, narrative_text: "Một buổi chiều yên ả.", complete: true, selected: true }], jobs: [] }), { status: 200 })));

    render(<AppShell owner={{ id: "owner-1", email: "owner@example.test" }} onLogout={() => undefined} />);

    const campaignSelect = await screen.findByRole("combobox", { name: "Chiến dịch hiện tại" });
    expect(campaignSelect).toHaveValue("campaign-1");
    expect(campaignSelect.closest("header")).toBeInTheDocument();
    expect(await screen.findByText("Một buổi chiều yên ả.")).toBeInTheDocument();
    const contextTrigger = screen.getByRole("button", { name: "Mở hồ sơ và ký ức" });
    expect(contextTrigger.closest("header")).toBeInTheDocument();
    expect(screen.getByRole("main").querySelector(".conversation-column")).toBeInTheDocument();
    expect(screen.getByRole("main").querySelector(".conversation-column .eyebrow")).not.toBeInTheDocument();
    expect(screen.getByTestId("generation-composer")).toBeInTheDocument();
    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Mùa hạ" })).not.toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(contextTrigger);
    expect(screen.getByRole("dialog", { name: "Hồ sơ và ký ức" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Đóng hồ sơ và ký ức" }));
    expect(contextTrigger).toHaveFocus();
  });

  it("locks imported campaigns until all four review acknowledgements are explicitly approved", async () => {
    const projection = { campaign: { id: "imported", title: "Imported", created_at: "2026-01-01", updated_at: "2026-01-01", archived_at: null }, branch: { id: "branch", name: "main", state_version: 1, checkpoint_id: "checkpoint" }, checkpoint: { id: "checkpoint", state_version: 1, parent_checkpoint_id: null, selected_revision_ids: [], retrieval_policy: "auto" }, profiles: {}, scene: null, transcript: [], jobs: [], import_review: { required: true, approved: false, review: {} } };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: "imported", title: "Imported", created_at: "2026-01-01", updated_at: "2026-01-01", archived_at: null }]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "imported", title: "Imported", branch_id: "branch", state_version: 1, checkpoint_id: "checkpoint", profiles: {} }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(projection), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ focus_scene_id: null, scenes: {} }), { status: 200 }))
      .mockResolvedValue(new Response(JSON.stringify(projection), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<AppShell owner={{ id: "owner", email: "owner@example.test" }} onLogout={() => undefined} />);
    expect(await screen.findByRole("heading", { name: "Kiểm tra checkpoint nhập" })).toBeInTheDocument();
    expect(screen.queryByTestId("generation-composer")).not.toBeInTheDocument();
    const checks = screen.getByRole("heading", { name: "Kiểm tra checkpoint nhập" }).closest("section")?.querySelectorAll("input[type=checkbox]");
    expect(checks).toHaveLength(4);
    expect(screen.getByRole("button", { name: /Duyệt checkpoint/ })).toBeDisabled();
    await waitFor(() => expect(checks?.[0]).toBeEnabled());
    for (const checkbox of Array.from(checks ?? [])) await userEvent.setup().click(checkbox);
    const approve = screen.getByRole("button", { name: /Duyệt checkpoint/ });
    expect(approve).toBeEnabled();
    await userEvent.setup().click(approve);
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/api/transfers/chatgpt/imported/review"), expect.objectContaining({ method: "POST" }));
  });

  it("keeps approval disabled when the actual snapshot cannot be loaded", async () => {
    vi.spyOn(api, "listMemory").mockRejectedValue(new Error("offline"));
    vi.spyOn(api, "getScene").mockResolvedValue({ focus_scene_id: null, scenes: {} });
    render(<ImportReviewPanel projection={reviewProjection() as never} onApproved={() => undefined} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Không thể tải đầy đủ");
    expect(screen.getByRole("button", { name: /Duyệt checkpoint/ })).toBeDisabled();
    expect(screen.getAllByRole("checkbox").every((checkbox) => (checkbox as HTMLInputElement).disabled)).toBe(true);
  });

  it("resets every acknowledgement when the checkpoint changes", async () => {
    mockReviewSnapshot();
    const { rerender } = render(<ImportReviewPanel projection={reviewProjection("checkpoint-a") as never} onApproved={() => undefined} />);
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getAllByRole("checkbox")[0]).toBeEnabled());
    for (const checkbox of screen.getAllByRole("checkbox")) await user.click(checkbox);
    expect(screen.getByRole("button", { name: /Duyệt checkpoint/ })).toBeEnabled();
    rerender(<ImportReviewPanel projection={reviewProjection("checkpoint-b") as never} onApproved={() => undefined} />);
    await waitFor(() => expect(screen.getAllByRole("checkbox").every((checkbox) => !(checkbox as HTMLInputElement).checked)).toBe(true));
    expect(screen.getByRole("button", { name: /Duyệt checkpoint/ })).toBeDisabled();
  });

  it("ignores a delayed approval after the campaign identity changes", async () => {
    mockReviewSnapshot();
    let resolveApproval: (value: { required: boolean; approved: boolean }) => void = () => undefined;
    vi.spyOn(api, "approveChatGptImport").mockReturnValue(new Promise((resolve) => { resolveApproval = resolve; }));
    const onApproved = vi.fn();
    const { rerender } = render(<ImportReviewPanel projection={reviewProjection("checkpoint-a", "campaign-a") as never} onApproved={onApproved} />);
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getAllByRole("checkbox")[0]).toBeEnabled());
    for (const checkbox of screen.getAllByRole("checkbox")) await user.click(checkbox);
    await user.click(screen.getByRole("button", { name: /Duyệt checkpoint/ }));
    rerender(<ImportReviewPanel projection={reviewProjection("checkpoint-b", "campaign-b") as never} onApproved={onApproved} />);
    resolveApproval({ required: false, approved: true });
    await waitFor(() => expect(screen.getByRole("button", { name: /Duyệt checkpoint/ })).toBeDisabled());
    expect(onApproved).not.toHaveBeenCalled();
  });

  it("refreshes after successful approval under StrictMode", async () => {
    mockReviewSnapshot();
    vi.spyOn(api, "approveChatGptImport").mockResolvedValue({ required: false, approved: true });
    const onApproved = vi.fn();
    render(<StrictMode><ImportReviewPanel projection={reviewProjection() as never} onApproved={onApproved} /></StrictMode>);
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getAllByRole("checkbox")[0]).toBeEnabled());
    for (const checkbox of screen.getAllByRole("checkbox")) await user.click(checkbox);
    await user.click(screen.getByRole("button", { name: /Duyệt checkpoint/ }));
    await waitFor(() => expect(onApproved).toHaveBeenCalledTimes(1));
  });

  it("does not surface a stale approval error after the campaign changes", async () => {
    mockReviewSnapshot();
    let rejectApproval: (reason?: unknown) => void = () => undefined;
    vi.spyOn(api, "approveChatGptImport").mockReturnValue(new Promise((_resolve, reject) => { rejectApproval = reject; }));
    const onApproved = vi.fn();
    const { rerender } = render(<ImportReviewPanel projection={reviewProjection("checkpoint-a", "campaign-a") as never} onApproved={onApproved} />);
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getAllByRole("checkbox")[0]).toBeEnabled());
    for (const checkbox of screen.getAllByRole("checkbox")) await user.click(checkbox);
    await user.click(screen.getByRole("button", { name: /Duyệt checkpoint/ }));
    rerender(<ImportReviewPanel projection={reviewProjection("checkpoint-b", "campaign-b") as never} onApproved={onApproved} />);
    rejectApproval(new Error("stale approval"));
    await waitFor(() => expect(screen.getByRole("button", { name: /Duyệt checkpoint/ })).toBeDisabled());
    expect(screen.queryByText("stale approval")).not.toBeInTheDocument();
  });
});
