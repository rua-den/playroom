import { afterEach, describe, expect, it, vi } from "vitest";
import { StrictMode } from "react";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { lastStoryStorageKey, recoverableJobCount, recoverableJobSummary } from "./AppShell";
import { AppShell, ImportReviewPanel } from "./AppShell";
import { api, ApiError } from "../api/client";
import type { CampaignProjection, CampaignSummary } from "../api/types";

vi.mock("./GenerationComposer", () => ({ GenerationComposer: () => <div data-testid="generation-composer"><textarea aria-label="Synthetic unsent draft" /></div> }));
vi.mock("./ProfileEditor", () => ({ ProfileEditor: () => <div data-testid="profile-editor" /> }));
vi.mock("./MemoryLibrary", () => ({ MemoryLibrary: () => <textarea aria-label="Memory mock draft" /> }));
vi.mock("./SceneEditor", () => ({ SceneEditor: () => <input aria-label="Scene mock draft" /> }));
vi.mock("./SettingsPanel", () => ({ SettingsPanel: () => <div data-testid="settings-panel" /> }));

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); window.history.replaceState(null, "", "/"); });

describe("recoverable job summary", () => {
  it("restores a story URL only when the authenticated catalog contains it", async () => {
    window.history.replaceState(null, "", "/?story=url-story");
    const projection = reviewProjection("cp", "url-story");
    projection.import_review.required = false;
    vi.spyOn(api, "listCampaigns").mockResolvedValue([projection.campaign]);
    const detail = vi.spyOn(api, "getCampaign").mockResolvedValue({ ...projection.campaign, branch_id: "branch", state_version: 1, checkpoint_id: "cp", profiles: {} });
    vi.spyOn(api, "getCampaignProjection").mockResolvedValue(projection);
    const { unmount } = render(<AppShell owner={{ id: "url-owner", email: "url@example.test" }} onLogout={() => undefined} />);
    expect(await screen.findByTestId("generation-composer")).toBeVisible();
    expect(detail).toHaveBeenCalledWith("url-story");
    unmount(); detail.mockClear();
    window.history.replaceState(null, "", "/?story=someone-elses-story");
    render(<AppShell owner={{ id: "another-url-owner", email: "url@example.test" }} onLogout={() => undefined} />);
    await screen.findByRole("button", { name: "Mở truyện" });
    expect(detail).not.toHaveBeenCalled();
    expect(window.location.search).toBe("");
  });

  it("does not restore a previous authentication session from history", async () => {
    window.history.replaceState(null, "", "/");
    vi.spyOn(api, "listCampaigns").mockResolvedValue([]);
    render(<AppShell owner={{ id: "new-history-owner", email: "new@example.test" }} onLogout={() => undefined} />);
    await screen.findByRole("button", { name: "Cài đặt" });
    const oldState = { playroom: { owner: "previous-owner", session: "previous-session", index: 9, view: { story: "private-story", details: true } } };
    act(() => {
      window.history.replaceState(oldState, "", "/?story=private-story");
      window.dispatchEvent(new PopStateEvent("popstate", { state: oldState }));
    });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(window.location.search).toBe("");
    expect(window.history.state.playroom.owner).toBe("new-history-owner");
  });

  it("navigates back through panels to library and forward without losing drafts or hash anchors", async () => {
    window.history.replaceState(null, "", "/");
    const projection = reviewProjection("cp", "history-story");
    projection.import_review.required = false;
    vi.spyOn(api, "listCampaigns").mockResolvedValue([projection.campaign]);
    vi.spyOn(api, "getCampaign").mockResolvedValue({ ...projection.campaign, branch_id: "branch", state_version: 1, checkpoint_id: "cp", profiles: {} });
    vi.spyOn(api, "getCampaignProjection").mockResolvedValue(projection);
    const user = userEvent.setup();
    render(<AppShell owner={{ id: "history-owner", email: "history@example.test" }} onLogout={() => undefined} />);
    await user.click(await screen.findByRole("button", { name: "Mở truyện" }));
    await user.click(await screen.findByRole("button", { name: "Mở hồ sơ và ký ức" }));
    await user.click(screen.getByRole("button", { name: "Ký ức" }));
    await user.type(screen.getByLabelText("Memory mock draft"), "saved draft");
    act(() => window.history.back());
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    act(() => window.history.forward());
    expect(await screen.findByRole("dialog", { name: "Hồ sơ và ký ức" })).toBeInTheDocument();
    expect(screen.getByLabelText("Memory mock draft")).toHaveValue("saved draft");
    act(() => window.history.back());
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Cài đặt" }));
    act(() => { window.location.hash = "cost-settings"; });
    await waitFor(() => expect(window.location.hash).toBe("#cost-settings"));
    act(() => window.history.back());
    await waitFor(() => expect(window.location.hash).toBe(""));
    expect(screen.getByRole("dialog", { name: "Cài đặt" })).toBeInTheDocument();
    act(() => window.history.back());
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    act(() => window.history.back());
    expect(await screen.findByRole("button", { name: "Đọc tiếp" })).toBeInTheDocument();
    act(() => window.history.forward());
    await waitFor(() => expect(screen.getByTestId("generation-composer")).toBeVisible());
    await user.click(screen.getByRole("button", { name: "Mở hồ sơ và ký ức" }));
    await user.click(screen.getByRole("button", { name: "Đóng hồ sơ và ký ức" }));
    await user.click(screen.getByRole("button", { name: "Mở hồ sơ và ký ức" }));
    act(() => window.history.back());
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByTestId("generation-composer")).toBeVisible();
    act(() => window.history.back());
    expect(await screen.findByRole("button", { name: "Đọc tiếp" })).toBeInTheDocument();
  });

  function reviewProjection(checkpoint = "checkpoint", campaign = "imported", branch = "branch", sourceConversationId?: string) {
    return { campaign: { id: campaign, title: campaign, created_at: "2026-01-01", updated_at: "2026-01-01", archived_at: null }, branch: { id: branch, name: "main", state_version: 1, checkpoint_id: checkpoint }, checkpoint: { id: checkpoint, state_version: 1, parent_checkpoint_id: null, selected_revision_ids: [], retrieval_policy: "auto" as const }, profiles: {}, scene: null, transcript: [], jobs: [], import_review: { required: true, approved: false, review: {}, source_conversation_id: sourceConversationId } };
  }

  function mockReviewSnapshot() {
    vi.spyOn(api, "listMemory").mockResolvedValue([]);
    vi.spyOn(api, "getScene").mockResolvedValue({ focus_scene_id: null, scenes: {} });
  }

  function branchStory() {
    const base: CampaignProjection = {
      campaign: { id: "campaign-branch", title: "Chuyện nhánh", created_at: "2026-01-01", updated_at: "2026-01-01", archived_at: null },
      branch: { id: "branch-main", name: "main", state_version: 2, checkpoint_id: "branch-main-head" },
      checkpoint: { id: "branch-main-head", state_version: 2, parent_checkpoint_id: null, selected_revision_ids: [], retrieval_policy: "auto" as const },
      profiles: {}, scene: null,
      transcript: [
        { revision_id: "revision-1", turn_id: "turn-1", turn_branch_id: "branch-main", turn_checkpoint_id: "commit-1", sequence: 1, action_text: "Mở hộp", revision: 1, narrative_text: "Tờ giấy xanh nằm trong hộp.", complete: true, selected: true },
        { revision_id: "revision-2", turn_id: "turn-2", turn_branch_id: "branch-main", turn_checkpoint_id: "commit-2", sequence: 2, action_text: "Cất tờ giấy", revision: 1, narrative_text: "Vy không nhìn thấy tờ giấy.", complete: true, selected: true },
      ],
      branches: [
        { id: "branch-main", name: "main", parent_branch_id: null, fork_checkpoint_id: null, state_version: 2, is_root: true },
      ],
      jobs: [],
    };
    const forked: CampaignProjection = {
      ...base,
      branch: { id: "branch-new", name: "Nhánh 2", state_version: 2, checkpoint_id: "branch-new-head" },
      checkpoint: { ...base.checkpoint, id: "branch-new-head" },
      transcript: [base.transcript[0]],
      branches: [base.branches![0], { id: "branch-new", name: "Nhánh 2", parent_branch_id: "branch-main", fork_checkpoint_id: "commit-1", fork_turn_sequence: 1, state_version: 2, is_root: false }],
    };
    return { base, forked };
  }

  function mockBranchStory() {
    const story = branchStory();
    vi.spyOn(api, "listCampaigns").mockResolvedValue([story.base.campaign]);
    vi.spyOn(api, "getCampaign").mockResolvedValue({ ...story.base.campaign, branch_id: "branch-main", state_version: 2, checkpoint_id: "branch-main-head", profiles: {} });
    vi.spyOn(api, "getCampaignProjection").mockImplementation(async (_campaignId, branchId) => branchId === "branch-new" ? story.forked : story.base);
    return story;
  }

  it("creates a branch from an earlier turn and continues reading the new branch", async () => {
    const story = mockBranchStory();
    const fork = vi.spyOn(api, "forkBranch").mockResolvedValue({ id: "branch-new", name: "Nhánh 2", campaign_id: "campaign-branch", parent_branch_id: "branch-main", fork_checkpoint_id: "commit-1", fork_turn_sequence: 1, state_version: 2, checkpoint_id: "branch-new-head", head_turn_id: "turn-1", inherited_turns: 1, is_root: false });
    const user = userEvent.setup();
    render(<AppShell owner={{ id: "branch-owner", email: "branch@example.test" }} onLogout={() => undefined} />);
    await user.click(await screen.findByRole("button", { name: "Mở truyện" }));
    expect(await screen.findByText("Tờ giấy xanh nằm trong hộp.")).toBeInTheDocument();
    expect(screen.getByText("Vy không nhìn thấy tờ giấy.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Tạo nhánh từ lượt 1" }));

    expect(fork).toHaveBeenCalledWith("campaign-branch", { source_branch_id: "branch-main", checkpoint_id: "commit-1", expected_state_version: 2 });
    expect(await screen.findByText("Đã tạo Nhánh 2 từ lượt 1.")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("Vy không nhìn thấy tờ giấy.")).not.toBeInTheDocument());
    expect(screen.getByLabelText("Nhánh truyện")).toHaveValue("branch-new");
    expect(screen.getByRole("option", { name: "Nhánh 2 · từ lượt 1" })).toBeInTheDocument();
    expect(story.forked.transcript.length).toBe(1);
  });

  it("switches the branch being read without reloading the story", async () => {
    const story = branchStory();
    story.base.branches = [...story.forked.branches!];
    vi.spyOn(api, "listCampaigns").mockResolvedValue([story.base.campaign]);
    vi.spyOn(api, "getCampaign").mockResolvedValue({ ...story.base.campaign, branch_id: "branch-main", state_version: 2, checkpoint_id: "branch-main-head", profiles: {} });
    const projection = vi.spyOn(api, "getCampaignProjection").mockImplementation(async (_campaignId, branchId) => branchId === "branch-new" ? story.forked : story.base);
    const user = userEvent.setup();
    render(<AppShell owner={{ id: "branch-switch-owner", email: "switch@example.test" }} onLogout={() => undefined} />);
    await user.click(await screen.findByRole("button", { name: "Mở truyện" }));
    expect(await screen.findByText("Vy không nhìn thấy tờ giấy.")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Nhánh truyện"), "branch-new");

    await waitFor(() => expect(screen.queryByText("Vy không nhìn thấy tờ giấy.")).not.toBeInTheDocument());
    expect(projection).toHaveBeenCalledWith("campaign-branch", "branch-new");
    expect(screen.getByLabelText("Nhánh truyện")).toHaveValue("branch-new");
    expect(screen.getByText("Tờ giấy xanh nằm trong hộp.")).toBeInTheDocument();
    expect(vi.mocked(api.getCampaign)).toHaveBeenCalledTimes(1);
  });

  it("keeps the current branch when creating one fails", async () => {
    mockBranchStory();
    vi.spyOn(api, "forkBranch").mockRejectedValue(new ApiError(409, "nhánh nguồn đã đổi"));
    const user = userEvent.setup();
    render(<AppShell owner={{ id: "branch-fail-owner", email: "fail@example.test" }} onLogout={() => undefined} />);
    await user.click(await screen.findByRole("button", { name: "Mở truyện" }));
    await screen.findByText("Tờ giấy xanh nằm trong hộp.");

    await user.click(screen.getByRole("button", { name: "Tạo nhánh từ lượt 1" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Không thể tạo nhánh: nhánh nguồn vừa thay đổi hoặc đang có lượt AI chưa xong. Hãy thử lại.");
    expect(screen.getByText("Vy không nhìn thấy tờ giấy.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Nhánh truyện")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tạo nhánh từ lượt 1" })).toBeEnabled();
  });

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
    const storyMenu = await screen.findByRole("button", { name: "Truyện và tác vụ" });
    expect(storyMenu.closest("header")).toBeInTheDocument();
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

  it("keeps editor drafts while switching tabs and closing/reopening context", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: "campaign-1", title: "Mùa hạ", created_at: "2026-01-01", updated_at: "2026-01-01", archived_at: null }]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "campaign-1", title: "Mùa hạ", created_at: "2026-01-01", updated_at: "2026-01-01", branch_id: "branch-1", state_version: 1, checkpoint_id: "checkpoint-1", profiles: {} }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ campaign: { id: "campaign-1", title: "Mùa hạ", created_at: "2026-01-01", updated_at: "2026-01-01", archived_at: null }, branch: { id: "branch-1", name: "Chính", state_version: 1, checkpoint_id: "checkpoint-1" }, checkpoint: { id: "checkpoint-1", state_version: 1, parent_checkpoint_id: null, selected_revision_ids: [], retrieval_policy: "auto" }, profiles: {}, scene: null, transcript: [], jobs: [] }), { status: 200 })));
    const user = userEvent.setup();
    render(<AppShell owner={{ id: "draft-owner", email: "owner@example.test" }} onLogout={() => undefined} />);
    await user.click(await screen.findByRole("button", { name: "Mở truyện" }));
    await user.click(await screen.findByRole("button", { name: "Mở hồ sơ và ký ức" }));
    await user.click(screen.getByRole("button", { name: "Ký ức" }));
    await user.type(screen.getByLabelText("Memory mock draft"), "giữ lại");
    await user.click(screen.getByRole("button", { name: "Cảnh" }));
    await user.click(screen.getByRole("button", { name: "Ký ức" }));
    expect(screen.getByLabelText("Memory mock draft")).toHaveValue("giữ lại");
    await user.click(screen.getByRole("button", { name: "Đóng hồ sơ và ký ức" }));
    await user.click(screen.getByRole("button", { name: "Mở hồ sơ và ký ức" }));
    expect(screen.getByLabelText("Memory mock draft")).toHaveValue("giữ lại");
  });

  it("isolates editor drafts when changing campaigns", async () => {
    const projectionFor = (id: string, branch: string) => ({ campaign: { id, title: id === "campaign-a" ? "Mùa hạ" : "Đêm mưa", created_at: "2026-01-01", updated_at: "2026-01-01", archived_at: null }, branch: { id: branch, name: "Chính", state_version: 1, checkpoint_id: `checkpoint-${id}` }, checkpoint: { id: `checkpoint-${id}`, state_version: 1, parent_checkpoint_id: null, selected_revision_ids: [], retrieval_policy: "auto" as const }, profiles: {}, scene: null, transcript: [], jobs: [] });
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: "campaign-a", title: "Mùa hạ", created_at: "2026-01-01", updated_at: "2026-01-01", archived_at: null }, { id: "campaign-b", title: "Đêm mưa", created_at: "2026-01-01", updated_at: "2026-01-01", archived_at: null }]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "campaign-a", title: "Mùa hạ", branch_id: "branch-a", state_version: 1, checkpoint_id: "checkpoint-campaign-a", profiles: {} }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(projectionFor("campaign-a", "branch-a")), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "campaign-b", title: "Đêm mưa", branch_id: "branch-b", state_version: 1, checkpoint_id: "checkpoint-campaign-b", profiles: {} }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(projectionFor("campaign-b", "branch-b")), { status: 200 })));
    const user = userEvent.setup();
    render(<AppShell owner={{ id: "scope-owner", email: "owner@example.test" }} onLogout={() => undefined} />);
    await user.click((await screen.findAllByRole("button", { name: "Mở truyện" }))[0]);
    await user.click(await screen.findByRole("button", { name: "Mở hồ sơ và ký ức" }));
    await user.click(screen.getByRole("button", { name: "Ký ức" }));
    await user.type(screen.getByLabelText("Memory mock draft"), "campaign-a draft");
    await user.click(screen.getByRole("button", { name: "Đóng hồ sơ và ký ức" }));
    await user.click(screen.getByRole("button", { name: "Truyện và tác vụ" }));
    await user.click(screen.getByRole("button", { name: "Đêm mưa" }));
    await user.click(await screen.findByRole("button", { name: "Mở hồ sơ và ký ức" }));
    await user.click(screen.getByRole("button", { name: "Ký ức" }));
    expect(screen.getByLabelText("Memory mock draft")).toHaveValue("");
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

  it("shows durable partial progress and keeps review locked until import completes", async () => {
    mockReviewSnapshot();
    const base = reviewProjection();
    const projection = {
      ...base,
      transcript: Array.from({ length: 100 }, (_, index) => ({
        revision_id: `revision-${index}`,
        turn_id: `turn-${index}`,
        sequence: index + 1,
        action_text: `action ${index}`,
        revision: 1,
        narrative_text: `narrative ${index}`,
        complete: true,
        selected: true,
      })),
      import_review: {
        ...base.import_review,
        import_status: "importing" as const,
        imported_turns: 100,
        paired_turns: 125,
      },
    };
    render(<ImportReviewPanel projection={projection as never} onApproved={() => undefined} />);
    expect(await screen.findByText(/Import chưa hoàn tất: đã lưu 100\/125/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: /Duyệt checkpoint/ })).toBeDisabled());
    expect(screen.getAllByRole("checkbox").every((checkbox) => (checkbox as HTMLInputElement).disabled)).toBe(true);
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

describe("account management navigation", () => {
  it("shows the account page only to admins and returns to the story library", async () => {
    vi.spyOn(api, "listCampaigns").mockResolvedValue([]);
    vi.spyOn(api, "listAccounts").mockResolvedValue([]);
    const user = userEvent.setup();
    const view = render(<AppShell owner={{ id: "reader-owner", email: "reader@example.test", is_admin: false }} onLogout={() => undefined} />);
    await screen.findByRole("button", { name: "Thư viện truyện" });
    expect(screen.queryByRole("button", { name: "Quản lý tài khoản" })).not.toBeInTheDocument();

    view.rerender(<AppShell owner={{ id: "admin-owner", email: "admin@example.test", username: "admin", is_admin: true }} onLogout={() => undefined} />);
    await user.click(await screen.findByRole("button", { name: "Quản lý tài khoản" }));
    expect(await screen.findByRole("heading", { name: "Quản lý tài khoản" })).toBeInTheDocument();
    expect(api.listAccounts).toHaveBeenCalledOnce();
    await user.click(screen.getByRole("button", { name: "Quay lại truyện" }));
    expect(await screen.findByRole("heading", { name: "Thư viện truyện" })).toBeInTheDocument();
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
    await user.click(await screen.findByRole("button", { name: "Mở hồ sơ và ký ức" }));
    act(() => window.history.back());
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    act(() => window.history.back());
    await screen.findByRole("button", { name: "Đọc tiếp" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    act(() => window.history.forward());
    await waitFor(() => expect(screen.getByTestId("generation-composer")).toBeVisible());
    await user.click(screen.getByRole("button", { name: "Truyện và tác vụ" }));
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

  it("groups story navigation once and preserves the unsent draft through actions and context", async () => {
    mockStories();
    const user = userEvent.setup();
    render(<AppShell owner={{ id: "reading-owner", email: "reader@example.test" }} onLogout={() => undefined} />);
    await user.click((await screen.findAllByRole("button", { name: "Mở truyện" }))[0]);
    const draft = await screen.findByRole("textbox", { name: "Synthetic unsent draft" });
    await user.type(draft, "Một dòng chưa gửi.");
    expect(screen.queryByRole("combobox", { name: "Truyện hiện tại" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Nhập ChatGPT" })).not.toBeInTheDocument();
    const trigger = screen.getByRole("button", { name: "Truyện và tác vụ" });
    expect(trigger.closest("header")).toBeInTheDocument();
    await user.click(trigger);
    const menu = screen.getByRole("dialog", { name: "Danh sách truyện" });
    expect(within(menu).getByRole("button", { name: "Mùa hạ" })).toHaveAttribute("aria-pressed", "true");
    await user.click(within(menu).getByRole("button", { name: "Tạo truyện mới" }));
    expect(screen.getByRole("dialog", { name: "Tạo truyện mới" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(trigger).toHaveFocus();
    expect(draft).toHaveValue("Một dòng chưa gửi.");
    await user.click(screen.getByRole("button", { name: "Mở hồ sơ và ký ức" }));
    await user.keyboard("{Escape}");
    expect(draft).toHaveValue("Một dòng chưa gửi.");
    expect(api.getCampaign).toHaveBeenCalledTimes(1);
  });

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
    const importTrigger = screen.getByRole("button", { name: "Truyện và tác vụ" });
    await user.click(importTrigger);
    await user.click(screen.getByRole("button", { name: "Nhập ChatGPT" }));
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
    await user.click(screen.getByRole("button", { name: "Nhập ChatGPT" }));
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

  it("puts the selected story first in the library DOM without changing campaign order", async () => {
    mockStories();
    window.localStorage.setItem(lastStoryStorageKey("selected-first-owner"), "story-b");
    const user = userEvent.setup();
    render(<AppShell owner={{ id: "selected-first-owner", email: "owner@example.test" }} onLogout={() => undefined} />);
    expect(await screen.findByRole("heading", { name: "Đêm mưa" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Thư viện truyện" }));
    const titles = Array.from(document.querySelectorAll(".story-library-grid .story-card h2")).map((heading) => heading.textContent);
    expect(titles).toEqual(["Đêm mưa", "Mùa hạ"]);
    expect(summaries.map((item) => item.id)).toEqual(["story-a", "story-b"]);
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

  it("offers a delete action and confirmation for each story", async () => {
    mockStories();
    render(<AppShell owner={{ id: "trash-owner", email: "trash@example.test" }} onLogout={() => undefined} />);
    const library = await screen.findByRole("heading", { name: "Thư viện truyện" });
    const card = library.closest("section")!.querySelector(".story-card")! as HTMLElement;
    expect(within(card).getByRole("button", { name: "Xoá truyện: Mùa hạ" })).toBeInTheDocument();
  });

  it("cancels without a request and deletes only the confirmed story", async () => {
    mockStories();
    const deleteSpy = vi.spyOn(api, "deleteCampaign").mockResolvedValue({ ...summaries[0], deleted_at: "2026-10-20T10:00:00Z" });
    const user = userEvent.setup();
    render(<AppShell owner={{ id: "delete-owner", email: "delete@example.test" }} onLogout={() => undefined} />);
    const card = (await screen.findByRole("heading", { name: "Mùa hạ" })).closest("article")!;
    await user.click(within(card).getByRole("button", { name: "Xoá truyện: Mùa hạ" }));
    expect(await screen.findByRole("dialog", { name: "Xoá truyện?" })).toHaveTextContent("Truyện “Mùa hạ” sẽ được chuyển vào Thùng rác");
    await user.click(screen.getByRole("button", { name: "Huỷ" }));
    expect(deleteSpy).not.toHaveBeenCalled();
    await user.click(within(card).getByRole("button", { name: "Xoá truyện: Mùa hạ" }));
    await user.click(screen.getByRole("button", { name: "Xoá truyện" }));
    await waitFor(() => expect(deleteSpy).toHaveBeenCalledWith("story-a"));
    expect(screen.queryByRole("heading", { name: "Mùa hạ" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Đêm mưa" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hoàn tác" })).toBeInTheDocument();
  });

  it("loads trash and restores only after backend acknowledgement", async () => {
    mockStories();
    vi.spyOn(api, "listCampaigns").mockImplementation(async (trashed = false) => trashed ? [{ ...summaries[0], deleted_at: "2026-10-20T10:00:00Z" }] : summaries);
    const restoreSpy = vi.spyOn(api, "restoreCampaign").mockResolvedValue(summaries[0]);
    const user = userEvent.setup();
    render(<AppShell owner={{ id: "restore-owner", email: "restore@example.test" }} onLogout={() => undefined} />);
    await user.click(await screen.findByRole("button", { name: "Thùng rác" }));
    expect(await screen.findByRole("heading", { name: "Mùa hạ" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Khôi phục: Mùa hạ" }));
    await waitFor(() => expect(restoreSpy).toHaveBeenCalledWith("story-a"));
    expect(screen.queryByRole("heading", { name: "Mùa hạ" })).not.toBeInTheDocument();
  });

  it("keeps the story and confirmation open when deletion fails", async () => {
    mockStories();
    vi.spyOn(api, "deleteCampaign").mockRejectedValue(new Error("synthetic delete failure"));
    const user = userEvent.setup();
    render(<AppShell owner={{ id: "failure-owner", email: "failure@example.test" }} onLogout={() => undefined} />);
    const card = (await screen.findByRole("heading", { name: "Mùa hạ" })).closest("article")!;
    await user.click(within(card).getByRole("button", { name: "Xoá truyện: Mùa hạ" }));
    await user.click(screen.getByRole("button", { name: "Xoá truyện" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Không thể chuyển truyện vào Thùng rác");
    expect(screen.getByRole("heading", { name: "Mùa hạ", hidden: true })).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Xoá truyện?" })).toBeInTheDocument();
  });

  it("sends one delete request while confirmation is pending", async () => {
    mockStories();
    let resolveDelete!: (summary: CampaignSummary) => void;
    const deleteSpy = vi.spyOn(api, "deleteCampaign").mockReturnValue(new Promise((resolve) => { resolveDelete = resolve; }));
    const user = userEvent.setup();
    render(<AppShell owner={{ id: "pending-owner", email: "pending@example.test" }} onLogout={() => undefined} />);
    const card = (await screen.findByRole("heading", { name: "Mùa hạ" })).closest("article")!;
    await user.click(within(card).getByRole("button", { name: "Xoá truyện: Mùa hạ" }));
    const confirm = screen.getByRole("button", { name: "Xoá truyện" });
    await user.click(confirm);
    await user.click(confirm);
    expect(deleteSpy).toHaveBeenCalledTimes(1);
    resolveDelete({ ...summaries[0], deleted_at: "2026-10-20T10:00:00Z" });
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Mùa hạ" })).not.toBeInTheDocument());
  });

  it("ignores a deferred trash failure after leaving Trash", async () => {
    mockStories();
    let rejectTrash!: (cause: Error) => void;
    vi.spyOn(api, "listCampaigns").mockImplementation(async (trashed = false) => {
      if (!trashed) return summaries;
      return new Promise((_, reject) => { rejectTrash = reject; });
    });
    const user = userEvent.setup();
    render(<AppShell owner={{ id: "trash-leave-owner", email: "trash-leave@example.test" }} onLogout={() => undefined} />);
    await user.click(await screen.findByRole("button", { name: "Thùng rác" }));
    await user.click(screen.getByRole("button", { name: "Thư viện" }));
    rejectTrash(new Error("late trash failure"));
    await waitFor(() => expect(screen.queryByText("Không thể tải Thùng rác.")).not.toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "Thư viện truyện" })).toBeInTheDocument();
  });

  it("does not resurrect a restored story from a deferred Trash response", async () => {
    mockStories();
    let listCalls = 0;
    let resolveLateTrash!: (items: CampaignSummary[]) => void;
    vi.spyOn(api, "listCampaigns").mockImplementation(async (trashed = false) => {
      if (!trashed) return summaries;
      listCalls += 1;
      if (listCalls === 2) return new Promise((resolve) => { resolveLateTrash = resolve; });
      return [{ ...summaries[0], deleted_at: "2026-10-20T10:00:00Z" }];
    });
    vi.spyOn(api, "restoreCampaign").mockResolvedValue(summaries[0]);
    const user = userEvent.setup();
    render(<AppShell owner={{ id: "late-trash-owner", email: "late-trash@example.test" }} onLogout={() => undefined} />);
    await user.click(await screen.findByRole("button", { name: "Thùng rác" }));
    await user.click(await screen.findByRole("button", { name: "Khôi phục: Mùa hạ" }));
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Mùa hạ" })).not.toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Thùng rác" }));
    resolveLateTrash([{ ...summaries[0], deleted_at: "2026-10-20T10:00:00Z" }]);
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Mùa hạ" })).not.toBeInTheDocument());
  });

  it("retains Undo after a failed restore", async () => {
    mockStories();
    vi.spyOn(api, "deleteCampaign").mockResolvedValue({ ...summaries[0], deleted_at: "2026-10-20T10:00:00Z" });
    vi.spyOn(api, "restoreCampaign").mockRejectedValue(new Error("restore failed"));
    const user = userEvent.setup();
    render(<AppShell owner={{ id: "undo-failure-owner", email: "undo-failure@example.test" }} onLogout={() => undefined} />);
    const card = (await screen.findByRole("heading", { name: "Mùa hạ" })).closest("article")!;
    await user.click(within(card).getByRole("button", { name: "Xoá truyện: Mùa hạ" }));
    await user.click(screen.getByRole("button", { name: "Xoá truyện" }));
    const undo = await screen.findByRole("button", { name: "Hoàn tác" });
    await user.click(undo);
    expect(await screen.findByRole("button", { name: "Hoàn tác" })).toBeInTheDocument();
  });

  it("keeps a pending Undo action and sends one restore request", async () => {
    mockStories();
    vi.spyOn(api, "deleteCampaign").mockResolvedValue({ ...summaries[0], deleted_at: "2026-10-20T10:00:00Z" });
    let resolveRestore!: (summary: CampaignSummary) => void;
    const restoreSpy = vi.spyOn(api, "restoreCampaign").mockReturnValue(new Promise((resolve) => { resolveRestore = resolve; }));
    const user = userEvent.setup();
    render(<AppShell owner={{ id: "undo-pending-owner", email: "undo-pending@example.test" }} onLogout={() => undefined} />);
    const card = (await screen.findByRole("heading", { name: "Mùa hạ" })).closest("article")!;
    await user.click(within(card).getByRole("button", { name: "Xoá truyện: Mùa hạ" }));
    await user.click(screen.getByRole("button", { name: "Xoá truyện" }));
    const undo = await screen.findByRole("button", { name: "Hoàn tác" });
    await user.click(undo);
    await user.click(screen.getByRole("button", { name: "Đang xử lý…" }));
    expect(restoreSpy).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Đang xử lý…" })).toBeDisabled();
    await act(async () => { resolveRestore(summaries[0]); });
    await waitFor(() => expect(screen.queryByRole("button", { name: "Đang xử lý…" })).not.toBeInTheDocument());
  });

  it("preserves the selected story when deleting a different story", async () => {
    mockStories();
    vi.spyOn(api, "deleteCampaign").mockResolvedValue({ ...summaries[1], deleted_at: "2026-10-20T10:00:00Z" });
    const user = userEvent.setup();
    render(<AppShell owner={{ id: "nonselected-delete-owner", email: "nonselected-delete@example.test" }} onLogout={() => undefined} />);
    await user.click((await screen.findAllByRole("button", { name: "Mở truyện" }))[0]);
    await screen.findByRole("heading", { name: "Mùa hạ" });
    await user.click(screen.getByRole("button", { name: "Thư viện truyện" }));
    const card = screen.getByRole("heading", { name: "Đêm mưa" }).closest("article")!;
    await user.click(within(card).getByRole("button", { name: "Xoá truyện: Đêm mưa" }));
    await user.click(screen.getByRole("button", { name: "Xoá truyện" }));
    expect(await screen.findByRole("heading", { name: "Mùa hạ" })).toBeInTheDocument();
  });

  it("ignores a late projection for a story that is no longer selected", async () => {
    mockStories();
    let resolveFirst!: (value: CampaignProjection) => void;
    vi.mocked(api.getCampaignProjection).mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; })).mockImplementation(async (id) => projection(id) as CampaignProjection);
    const user = userEvent.setup();
    render(<AppShell owner={{ id: "late-projection-owner", email: "late-projection@example.test" }} onLogout={() => undefined} />);
    const openButtons = await screen.findAllByRole("button", { name: "Mở truyện" });
    await user.click(openButtons[0]);
    await user.click(screen.getByRole("button", { name: "Thư viện truyện" }));
    await user.click(screen.getByRole("button", { name: "Mở truyện" }));
    resolveFirst(projection("story-a") as CampaignProjection);
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Mùa hạ" })).not.toBeInTheDocument());
  });

  it("keeps the selected story projection alive when reopening the same story", async () => {
    mockStories();
    window.localStorage.setItem(lastStoryStorageKey("same-story-owner"), "story-a");
    let resolveProjection!: (value: CampaignProjection) => void;
    vi.mocked(api.getCampaignProjection).mockReturnValueOnce(new Promise((resolve) => { resolveProjection = resolve; }));
    const user = userEvent.setup();
    render(<AppShell owner={{ id: "same-story-owner", email: "same-story@example.test" }} onLogout={() => undefined} />);
    await user.click(await screen.findByRole("button", { name: "Thư viện truyện" }));
    await user.click(within(screen.getByRole("heading", { name: "Thư viện truyện" }).closest("section")!).getByRole("button", { name: "Đọc tiếp" }));
    resolveProjection(projection("story-a") as CampaignProjection);
    expect(await screen.findByRole("heading", { name: "Mùa hạ" })).toBeInTheDocument();
  });
});
