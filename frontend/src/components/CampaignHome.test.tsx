import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "./AppShell";
import { Markdown } from "./Markdown";

const owner = { id: "owner-1", email: "owner@example.test" };
const campaign = (id: string, title: string) => ({ id, title, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", archived_at: null });
const projection = (id: string, title: string, text: string) => ({
  campaign: campaign(id, title),
  branch: { id: `branch-${id}`, name: "main", state_version: 1, checkpoint_id: `checkpoint-${id}` },
  checkpoint: { id: `checkpoint-${id}`, state_version: 1, parent_checkpoint_id: null, selected_revision_ids: [] },
  profiles: { world: { profile_key: "world", kind: "world" as const, version: 1, data: { name: "World", description: "A world" } }, persona: { profile_key: "persona", kind: "persona" as const, version: 1, data: { name: "Player", description: "A player" } } },
  scene: null,
  transcript: text ? [{ revision_id: `revision-${id}`, turn_id: `turn-${id}`, sequence: 1, action_text: "Look", revision: 1, narrative_text: text, complete: true, selected: true }] : [],
  jobs: [],
});

afterEach(() => vi.restoreAllMocks());

describe("CampaignHome", () => {
  it("creates a campaign with UUID characters and aliases", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "campaign-new", title: "Bản đồ", branch_id: "branch-new", character_ids: ["character-new"] }), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...campaign("campaign-new", "Bản đồ"), branch_id: "branch-new", state_version: 1, checkpoint_id: "checkpoint-new", profiles: {} }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(projection("campaign-new", "Bản đồ", "")), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<AppShell owner={owner} onLogout={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "+ Tạo truyện mới" }));
    await user.type(screen.getByLabelText("Tên truyện"), "Bản đồ");
    await user.type(screen.getByLabelText("Tên thế giới"), "Miền sương");
    await user.type(screen.getByLabelText("Mô tả thế giới"), "Một thung lũng");
    await user.type(screen.getByLabelText("Tên persona"), "Linh");
    await user.type(screen.getByLabelText("Mô tả persona"), "Người tìm đường");
    await user.click(screen.getByRole("button", { name: "Thêm nhân vật" }));
    const characterName = screen.getByLabelText("Tên nhân vật 1");
    await user.type(characterName, "An");
    await user.type(screen.getByLabelText("Bí danh nhân vật 1"), "Bóng đêm, Người gác");
    await user.click(screen.getByRole("button", { name: "Lưu truyện" }));
    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(2));
    const payload = JSON.parse(fetchMock.mock.calls[1][1].body as string);
    expect(payload).toMatchObject({ title: "Bản đồ", world: { name: "Miền sương", description: "Một thung lũng" }, persona: { name: "Linh", description: "Người tìm đường" } });
    expect(payload.characters).toHaveLength(1);
    expect(payload.characters[0]).toMatchObject({ name: "An", aliases: ["Bóng đêm", "Người gác"] });
    expect(payload.characters[0].id).toMatch(/^[0-9a-f-]{36}$/i);
  });

  it("keeps create input after a server failure", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "failed" }), { status: 500 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<AppShell owner={owner} onLogout={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "+ Tạo truyện mới" }));
    await user.type(screen.getByLabelText("Tên truyện"), "Không mất bản nháp");
    await user.type(screen.getByLabelText("Tên thế giới"), "Thế giới thử");
    await user.type(screen.getByLabelText("Tên persona"), "Persona thử");
    await user.click(screen.getByRole("button", { name: "Lưu truyện" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Không thể tạo truyện");
    expect(screen.getByLabelText("Tên truyện")).toHaveValue("Không mất bản nháp");
    expect(screen.getByLabelText("Tên thế giới")).toHaveValue("Thế giới thử");
    expect(screen.getByLabelText("Tên persona")).toHaveValue("Persona thử");
  });

  it("requires a character name and does not submit during IME composition", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<AppShell owner={owner} onLogout={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "+ Tạo truyện mới" }));
    await user.type(screen.getByLabelText("Tên truyện"), "Bản nháp");
    await user.type(screen.getByLabelText("Tên thế giới"), "Thế giới");
    await user.type(screen.getByLabelText("Tên persona"), "Persona");
    await user.click(screen.getByRole("button", { name: "Thêm nhân vật" }));
    const character = screen.getByLabelText("Tên nhân vật 1");
    expect(character).toBeRequired();
    await user.type(character, "An");
    const form = document.querySelector("form.campaign-form")!;
    const submitEvent = new Event("submit", { bubbles: true, cancelable: true });
    Object.defineProperty(submitEvent, "isComposing", { value: true });
    form.dispatchEvent(submitEvent);
    expect(submitEvent.defaultPrevented).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("clears old story and jobs while switching campaigns", async () => {
    let resolveSecond!: (response: Response) => void;
    const secondProjection = new Promise<Response>((resolve) => { resolveSecond = resolve; });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([campaign("one", "Một chiến dịch"), campaign("two", "Hai chiến dịch")]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...campaign("one", "Một chiến dịch"), branch_id: "branch-one", state_version: 1, checkpoint_id: "checkpoint-one", profiles: {} }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(projection("one", "Một chiến dịch", "Câu cũ")), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...campaign("two", "Hai chiến dịch"), branch_id: "branch-two", state_version: 1, checkpoint_id: "checkpoint-two", profiles: {} }), { status: 200 }))
      .mockReturnValueOnce(secondProjection);
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<AppShell owner={owner} onLogout={vi.fn()} />);
    await user.click((await screen.findAllByRole("button", { name: "Mở truyện" }))[0]);
    expect(await screen.findByText("Câu cũ")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Hai chiến dịch" }));
    expect(screen.queryByText("Câu cũ")).not.toBeInTheDocument();
    resolveSecond(new Response(JSON.stringify(projection("two", "Hai chiến dịch", "Câu mới")), { status: 200 }));
    expect(await screen.findByText("Câu mới")).toBeInTheDocument();
  });

  it("opens and closes campaign drawer and profile sheet with touch targets", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([campaign("one", "Một chiến dịch")]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...campaign("one", "Một chiến dịch"), branch_id: "branch-one", state_version: 1, checkpoint_id: "checkpoint-one", profiles: {} }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(projection("one", "Một chiến dịch", "Câu chuyện")), { status: 200 })));
    const user = userEvent.setup();
    render(<AppShell owner={owner} onLogout={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "Mở truyện" }));
    await screen.findByText("Câu chuyện");
    const drawerButton = screen.getByRole("button", { name: "Truyện" });
    await user.click(drawerButton);
    const drawer = screen.getByRole("dialog", { name: "Danh sách truyện" });
    expect(drawer).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Đóng danh sách truyện" })).toHaveFocus();
    expect(drawerButton).toHaveClass("touch-target");
    await user.keyboard("{Escape}");
    expect(drawerButton).toHaveFocus();
    await user.click(drawerButton);
    const reopenedDrawer = screen.getByRole("dialog", { name: "Danh sách truyện" });
    const drawerCampaign = within(reopenedDrawer).getByRole("button", { name: "Một chiến dịch" });
    expect(drawerCampaign).toHaveAttribute("aria-pressed", "true");
    await user.click(drawerCampaign);
    expect(screen.queryByRole("dialog", { name: "Danh sách chiến dịch" })).not.toBeInTheDocument();
    expect(drawerButton).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "AI đang nhớ gì" }));
    expect(screen.getByRole("dialog", { name: "Hồ sơ và ký ức" })).toBeInTheDocument();
    expect(within(screen.getByRole("dialog", { name: "Hồ sơ và ký ức" })).getByRole("region", { name: "Chỉnh sửa hồ sơ" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Đóng hồ sơ và ký ức" })).toHaveFocus();
    await user.keyboard("{Tab}");
    expect(screen.getByRole("button", { name: "Hồ sơ" })).toHaveFocus();
    await user.keyboard("{Shift>}{Tab}{/Shift}");
    expect(screen.getByRole("button", { name: "Đóng hồ sơ và ký ức" })).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "Đóng hồ sơ và ký ức" }));
    expect(screen.queryByRole("dialog", { name: "Hồ sơ và ký ức" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "AI đang nhớ gì" })).toHaveFocus();
  });

  it("shows a shell-level load error instead of the empty create state", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValueOnce(new TypeError("offline")));
    render(<AppShell owner={owner} onLogout={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Không thể tải thư viện truyện");
    expect(screen.queryByRole("button", { name: "Tạo truyện đầu tiên" })).not.toBeInTheDocument();
  });
});

describe("Markdown", () => {
  it("renders readable paragraphs without creating raw HTML nodes", () => {
    const { container } = render(<Markdown source={"# Chương một\n\nMột đoạn **đậm**.\n\n<script>alert('x')</script>"} />);
    expect(screen.getByRole("heading", { name: "Chương một" })).toBeInTheDocument();
    expect(screen.getByText(/Một đoạn/)).toBeInTheDocument();
    expect(container.querySelector("script")).toBeNull();
  });
});
