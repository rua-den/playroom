import { afterEach, describe, expect, it, vi } from "vitest";
import { StrictMode } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { lastStoryStorageKey, recoverableJobCount, recoverableJobSummary } from "./AppShell";
import { AppShell, ImportReviewPanel } from "./AppShell";
import { api } from "../api/client";
import type { CampaignProjection } from "../api/types";

vi.mock("./GenerationComposer", () => ({ GenerationComposer: () => <div data-testid="generation-composer" /> }));
vi.mock("./ProfileEditor", () => ({ ProfileEditor: () => <div data-testid="profile-editor" /> }));
vi.mock("./MemoryLibrary", () => ({ MemoryLibrary: () => <div data-testid="memory-library" /> }));
vi.mock("./SceneEditor", () => ({ SceneEditor: () => <div data-testid="scene-editor" /> }));
vi.mock("./SettingsPanel", () => ({ SettingsPanel: () => <div data-testid="settings-panel" /> }));

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("recoverable job summary", () => {
  function reviewProjection(checkpoint = "checkpoint", campaign = "imported", branch = "branch", sourceConversationId?: string) {
    return { campaign: { id: campaign, title: campaign, created_at: "2026-01-01", updated_at: "2026-01-01", archived_at: null }, branch: { id: branch, name: "main", state_version: 1, checkpoint_id: checkpoint }, checkpoint: { id: checkpoint, state_version: 1, parent_checkpoint_id: null, selected_revision_ids: [], retrieval_policy: "auto" as const }, profiles: {}, scene: null, transcript: [], jobs: [], import_review: { required: true, approved: false, review: {}, source_conversation_id: sourceConversationId } };
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
    await userEvent.setup().click(await screen.findByRole("button", { name: "Mở truyện" }));
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

    await userEvent.setup().click(await screen.findByRole("button", { name: "Mở truyện" }));
    const campaignSelect = await screen.findByRole("combobox", { name: "Truyện hiện tại" });
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
    await userEvent.setup().click(await screen.findByRole("button", { name: "Mở truyện" }));
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

  it("shows structured profile, scene, and knowledge references with readable labels and IDs", async () => {
    vi.spyOn(api, "listMemory").mockResolvedValue([{ memory_id: "memory-1", id: "version-1", version: 1, kind: "lore", text: "A sealed note", origin: "import", status: "pending", pinned: false, source_revision_ids: [], entity_ids: ["npc-1"], knowledge_scope: "known_by", known_by: ["npc-1"] }]);
    vi.spyOn(api, "getScene").mockResolvedValue({ focus_scene_id: "scene-1", scenes: { "scene-1": { id: "scene-1", name: "Market", present_ids: ["npc-1"], participant_ids: ["npc-1"], role: "watcher", notes: "Rainy" } } });
    const projection = { ...reviewProjection(), profiles: {
      persona: { profile_key: "persona", kind: "persona", version: 1, data: { id: "persona-1", name: "Lan", traits: { agency: "player" } } },
      "character:npc-1": { profile_key: "character:npc-1", kind: "character", version: 1, data: { id: "npc-1", name: "Vy", role: "scout", notes: "Quiet voice" } },
    } };
    render(<ImportReviewPanel projection={projection as never} onApproved={() => undefined} />);
    expect(await screen.findByText("Lan")).toBeInTheDocument();
    expect(screen.getByText("persona-1")).toBeInTheDocument();
    expect(screen.getAllByText(/Vy \(npc-1\)/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Nhân vật biết: Vy \(npc-1\)/)).toBeInTheDocument();
    expect(screen.getAllByText("role").length).toBeGreaterThan(0);
    expect(screen.getByText(/Rainy/)).toBeInTheDocument();
    expect(screen.getByText("participant_ids")).toBeInTheDocument();
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

  it("resets acknowledgements when campaign, branch, or source changes with the same checkpoint", async () => {
    mockReviewSnapshot();
    const { rerender } = render(<ImportReviewPanel projection={reviewProjection("same-checkpoint", "campaign-a", "branch-a", "source-a") as never} onApproved={() => undefined} />);
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getAllByRole("checkbox")[0]).toBeEnabled());
    for (const checkbox of screen.getAllByRole("checkbox")) await user.click(checkbox);
    expect(screen.getByRole("button", { name: /Duyệt checkpoint/ })).toBeEnabled();
    rerender(<ImportReviewPanel projection={reviewProjection("same-checkpoint", "campaign-b", "branch-b", "source-b") as never} onApproved={() => undefined} />);
    await waitFor(() => expect(screen.getAllByRole("checkbox").every((checkbox) => !(checkbox as HTMLInputElement).checked)).toBe(true));
    expect(screen.getByRole("button", { name: /Duyệt checkpoint/ })).toBeDisabled();
  });

  it("does not let an old snapshot enable a changed source identity", async () => {
    let resolveOldMemory: (value: never[]) => void = () => undefined;
    let resolveOldScene: (value: { focus_scene_id: null; scenes: Record<string, never> }) => void = () => undefined;
    vi.spyOn(api, "listMemory").mockImplementationOnce(() => new Promise((resolve) => { resolveOldMemory = resolve; }))
      .mockResolvedValue([]);
    vi.spyOn(api, "getScene").mockImplementationOnce(() => new Promise((resolve) => { resolveOldScene = resolve; }))
      .mockResolvedValue({ focus_scene_id: null, scenes: {} });
    const { rerender } = render(<ImportReviewPanel projection={reviewProjection("same-checkpoint", "campaign-a", "branch-a", "source-a") as never} onApproved={() => undefined} />);
    rerender(<ImportReviewPanel projection={reviewProjection("same-checkpoint", "campaign-a", "branch-a", "source-b") as never} onApproved={() => undefined} />);
    resolveOldMemory([]);
    resolveOldScene({ focus_scene_id: null, scenes: {} });
    expect(screen.getByRole("button", { name: /Duyệt checkpoint/ })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Đang tải snapshot");
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

describe("auxiliary modal routes", () => {
  it("keeps the library mounted and preserves an unsent create draft when the modal closes", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(new Response("[]", { status: 200 })));
    const user = userEvent.setup();
    render(<AppShell owner={{ id: "modal-owner", email: "owner@example.test" }} onLogout={() => undefined} />);
    const open = await screen.findByRole("button", { name: "+ Tạo truyện mới" });
    const libraryHeading = screen.getByRole("heading", { name: "Thư viện truyện" });
    await user.click(open);
    const dialog = await screen.findByRole("dialog", { name: "Tạo truyện mới" });
    expect(libraryHeading).toBeInTheDocument();
    expect(libraryHeading.closest(".app-shell")?.parentElement?.hasAttribute("inert")).toBe(true);
    await user.type(screen.getByLabelText("Tên truyện"), "Draft story");
    await user.keyboard("{Escape}");
    await waitFor(() => expect(open).toHaveFocus());
    await user.click(open);
    expect(await screen.findByRole("dialog", { name: "Tạo truyện mới" })).toBe(dialog);
    expect(screen.getByLabelText("Tên truyện")).toHaveValue("Draft story");
  });

  it("shows create feedback only after server acknowledgement and clears a completed draft", async () => {
    let resolveCreate!: (response: Response) => void;
    const createResponse = new Promise<Response>((resolve) => { resolveCreate = resolve; });
    const detail = { id: "created-story", title: "Created story", created_at: "2026-10-19", updated_at: "2026-10-19", archived_at: null, branch_id: "created-branch", state_version: 1, checkpoint_id: "created-checkpoint", profiles: {} };
    const projection = { campaign: detail, branch: { id: "created-branch", name: "main", state_version: 1, checkpoint_id: "created-checkpoint" }, checkpoint: { id: "created-checkpoint", state_version: 1, parent_checkpoint_id: null, selected_revision_ids: [], retrieval_policy: "auto" as const }, profiles: {}, scene: null, transcript: [], jobs: [] };
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(new Response("[]", { status: 200 }))
      .mockImplementationOnce(() => createResponse)
      .mockResolvedValueOnce(new Response(JSON.stringify(detail), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(projection), { status: 200 })));
    const user = userEvent.setup();
    render(<AppShell owner={{ id: "ack-owner", email: "owner@example.test" }} onLogout={() => undefined} />);
    await user.click(await screen.findByRole("button", { name: "+ Tạo truyện mới" }));
    await user.type(screen.getByLabelText("Tên truyện"), "Created story");
    await user.type(screen.getByLabelText("Tên thế giới"), "World");
    await user.type(screen.getByLabelText("Tên persona"), "Player");
    await user.click(screen.getByRole("button", { name: "Lưu truyện" }));
    expect(screen.queryByText("Đã tạo truyện mới.")).not.toBeInTheDocument();
    resolveCreate(new Response(JSON.stringify({ id: "created-story", title: "Created story", branch_id: "created-branch", character_ids: [] }), { status: 200 }));
    expect(await screen.findByText("Đã tạo truyện mới.")).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Tạo truyện mới" }));
    expect(screen.getByLabelText("Tên truyện")).toHaveValue("");
  });
});

describe("story library navigation and last-story persistence", () => {
  afterEach(() => { try { window.localStorage.clear(); } catch { /* blocked storage is part of coverage */ } });
  const summaries = [
    { id: "story-a", title: "Mùa hạ", created_at: "2026-01-01", updated_at: "2026-01-02", archived_at: null },
    { id: "story-b", title: "Đêm mưa", created_at: "2026-01-01", updated_at: "2026-01-03", archived_at: null },
  ];
  const projection = (id: string) => ({ campaign: { ...summaries.find((item) => item.id === id)!, id }, branch: { id: `branch-${id}`, name: "main", state_version: 1, checkpoint_id: `checkpoint-${id}` }, checkpoint: { id: `checkpoint-${id}`, state_version: 1, parent_checkpoint_id: null, selected_revision_ids: [], retrieval_policy: "auto" as const }, profiles: {}, scene: null, transcript: [], jobs: [] });

  function mockStories() {
    vi.spyOn(api, "listCampaigns").mockResolvedValue(summaries);
    vi.spyOn(api, "getCampaign").mockImplementation(async (id) => ({ ...summaries.find((item) => item.id === id)!, branch_id: `branch-${id}`, state_version: 1, checkpoint_id: `checkpoint-${id}`, profiles: {} }));
    vi.spyOn(api, "getCampaignProjection").mockImplementation(async (id) => projection(id));
  }

  it("keeps story creation and both import routes available from the story menu", async () => {
    mockStories();
    const user = userEvent.setup();
    render(<AppShell owner={{ id: "mobile-menu-owner", email: "owner@example.test" }} onLogout={() => undefined} />);
    await user.click((await screen.findAllByRole("button", { name: "Mở truyện" }))[0]);
    await user.click(await screen.findByRole("button", { name: "Truyện và tác vụ" }));
    const storyMenu = screen.getByRole("dialog", { name: "Danh sách truyện" });
    expect(within(storyMenu).getByRole("button", { name: "Mùa hạ" })).toBeInTheDocument();

    await user.click(within(storyMenu).getByRole("button", { name: "Tạo truyện mới" }));
    expect(await screen.findByRole("dialog", { name: "Tạo truyện mới" })).toBeInTheDocument();
    await user.keyboard("{Escape}");

    await user.click(screen.getByRole("button", { name: "Truyện và tác vụ" }));
    const chatMenu = screen.getByRole("dialog", { name: "Danh sách truyện" });
    await user.click(within(chatMenu).getByRole("button", { name: "Nhập ChatGPT" }));
    expect(await screen.findByRole("dialog", { name: "Nhập hội thoại ChatGPT" })).toBeInTheDocument();
    await user.keyboard("{Escape}");

    await user.click(screen.getByRole("button", { name: "Truyện và tác vụ" }));
    const legacyMenu = screen.getByRole("dialog", { name: "Danh sách truyện" });
    await user.click(within(legacyMenu).getByRole("button", { name: "Nhập Legacy" }));
    expect(await screen.findByRole("dialog", { name: "Nhập Legacy Story Bundle" })).toBeInTheDocument();
  });

  it("keeps the real ChatGPT import metadata draft and current story across modal close and reopen", async () => {
    mockStories();
    vi.spyOn(api, "previewChatGptImport").mockResolvedValue({
      turn_count: 1,
      skipped_messages: 0,
      warnings: [],
      sample_first: { action_text: "Synthetic player text", narrative_text: "Synthetic assistant text" },
      sample_last: { action_text: "Synthetic player text", narrative_text: "Synthetic assistant text" },
    } as never);
    window.localStorage.setItem(lastStoryStorageKey("import-owner"), "story-b");
    const user = userEvent.setup();
    render(<AppShell owner={{ id: "import-owner", email: "import@example.test" }} onLogout={() => undefined} />);

    expect(await screen.findByRole("heading", { name: "Đêm mưa" })).toBeInTheDocument();
    const importTrigger = screen.getByRole("button", { name: "Nhập ChatGPT" });
    await user.click(importTrigger);
    expect(await screen.findByRole("dialog", { name: "Nhập hội thoại ChatGPT" })).toBeInTheDocument();

    const exportFile = new File([
      JSON.stringify([{ id: "synthetic-thread", title: "Synthetic thread", current_node: "node-1", mapping: {} }]),
    ], "conversations.json", { type: "application/json" });
    await user.upload(screen.getByLabelText("Tệp xuất từ ChatGPT"), exportFile);
    await user.click(await screen.findByRole("button", { name: "Xem trước thread này" }));
    const title = await screen.findByLabelText("Tên chiến dịch mới");
    await user.clear(title);
    await user.type(title, "Nháp hội thoại giữ lại");
    await user.clear(screen.getByLabelText("Thế giới"));
    await user.type(screen.getByLabelText("Thế giới"), "Thành phố mưa");
    await user.clear(screen.getByLabelText("Persona người chơi"));
    await user.type(screen.getByLabelText("Persona người chơi"), "Người kể chuyện");

    expect(document.querySelector(".workspace-grid h1")).toHaveTextContent("Đêm mưa");
    expect(document.querySelector(".story-library") ?? document.querySelector(".workspace-grid")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(importTrigger).toHaveFocus();

    await user.click(importTrigger);
    expect(await screen.findByRole("dialog", { name: "Nhập hội thoại ChatGPT" })).toBeInTheDocument();
    expect(screen.getByLabelText("Tên chiến dịch mới")).toHaveValue("Nháp hội thoại giữ lại");
    expect(screen.getByLabelText("Thế giới")).toHaveValue("Thành phố mưa");
    expect(screen.getByLabelText("Persona người chơi")).toHaveValue("Người kể chuyện");
    expect(document.querySelector(".workspace-grid h1")).toHaveTextContent("Đêm mưa");
  });

  it("opens the library without loading a story until the user chooses one", async () => {
    mockStories();
    render(<AppShell owner={{ id: "library-owner", email: "owner@example.test" }} onLogout={() => undefined} />);
    expect(await screen.findByRole("heading", { name: "Thư viện truyện" })).toBeInTheDocument();
    expect(api.getCampaign).not.toHaveBeenCalled();
    const library = screen.getByRole("heading", { name: "Thư viện truyện" }).closest("section")!;
    await userEvent.setup().click(within(library).getAllByRole("button", { name: "Mở truyện" })[0]);
    expect(await screen.findByRole("heading", { name: "Mùa hạ" })).toBeInTheDocument();
    expect(api.getCampaign).toHaveBeenCalledWith("story-a");
  });

  it("explains the empty library and keeps the existing create and import actions", async () => {
    vi.spyOn(api, "listCampaigns").mockResolvedValue([]);
    render(<AppShell owner={{ id: "empty-library-owner", email: "owner@example.test" }} onLogout={() => undefined} />);
    expect(await screen.findByRole("heading", { name: "Chưa có truyện nào" })).toBeInTheDocument();
    expect(document.querySelector(".library-empty svg")).toHaveAttribute("aria-hidden", "true");
    const library = screen.getByRole("heading", { name: "Thư viện truyện" }).closest("section")!;
    expect(within(library).getByRole("button", { name: "+ Tạo truyện mới" })).toBeInTheDocument();
    expect(within(library).getByRole("button", { name: "Nhập hội thoại ChatGPT" })).toBeInTheDocument();
    expect(within(library).getByRole("button", { name: "Nhập Legacy Bundle" })).toBeInTheDocument();
  });

  it("offers the context panel only after the selected story projection is ready", async () => {
    mockStories();
    let resolveProjection: (value: CampaignProjection) => void = () => undefined;
    vi.mocked(api.getCampaignProjection).mockReturnValueOnce(new Promise((resolve) => { resolveProjection = resolve; }));
    const user = userEvent.setup();
    render(<AppShell owner={{ id: "pending-context-owner", email: "owner@example.test" }} onLogout={() => undefined} />);
    await user.click((await screen.findAllByRole("button", { name: "Mở truyện" }))[0]);
    const storyMenuTrigger = await screen.findByRole("button", { name: "Truyện và tác vụ" });
    expect(screen.queryByRole("button", { name: "AI đang nhớ gì" })).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Hồ sơ và ký ức" })).not.toBeInTheDocument();

    resolveProjection(projection("story-a") as CampaignProjection);
    const contextTrigger = await screen.findByRole("button", { name: "AI đang nhớ gì" });
    expect(contextTrigger).toBeInTheDocument();
    await user.click(contextTrigger);
    expect(await screen.findByRole("dialog", { name: "Hồ sơ và ký ức" })).toBeInTheDocument();
    expect(storyMenuTrigger).toBeInTheDocument();
  });

  it("restores only an accessible last story and isolates owners", async () => {
    mockStories();
    window.localStorage.setItem(lastStoryStorageKey("owner-a"), "story-b");
    const first = render(<AppShell owner={{ id: "owner-a", email: "a@example.test" }} onLogout={() => undefined} />);
    expect(await screen.findByRole("heading", { name: "Đêm mưa" })).toBeInTheDocument();
    vi.mocked(api.getCampaign).mockClear();
    vi.mocked(api.listCampaigns).mockRejectedValueOnce(new Error("owner load failed"));
    first.rerender(<AppShell owner={{ id: "owner-b", email: "b@example.test" }} onLogout={() => undefined} />);
    expect(await screen.findByRole("heading", { name: "Thư viện truyện" })).toBeInTheDocument();
    expect(screen.queryByText("Đêm mưa")).not.toBeInTheDocument();
    expect(api.getCampaign).not.toHaveBeenCalled();
  });

  it("falls back to the library when storage is stale or blocked", async () => {
    mockStories();
    window.localStorage.setItem(lastStoryStorageKey("stale-owner"), "missing-story");
    const stale = render(<AppShell owner={{ id: "stale-owner", email: "stale@example.test" }} onLogout={() => undefined} />);
    expect(await screen.findByRole("heading", { name: "Thư viện truyện" })).toBeInTheDocument();
    stale.unmount();
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    render(<AppShell owner={{ id: "blocked-owner", email: "blocked@example.test" }} onLogout={() => undefined} />);
    expect(await screen.findByRole("heading", { name: "Thư viện truyện" })).toBeInTheDocument();
    await userEvent.setup().click(within(screen.getByRole("heading", { name: "Thư viện truyện" }).closest("section")!).getAllByRole("button", { name: "Mở truyện" })[0]);
    expect(await screen.findByRole("heading", { name: "Mùa hạ" })).toBeInTheDocument();
  });
});
