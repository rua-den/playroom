import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ProfileEditor } from "./ProfileEditor";
import { ToastProvider } from "./Toast";

const base = { branchId: "branch-1", stateVersion: 4, campaignId: "campaign-1" };

describe("ProfileEditor", () => {
  it("shows save success only after the server acknowledgement", async () => {
    let resolveSave!: (response: Response) => void;
    const save = new Promise<Response>((resolve) => { resolveSave = resolve; });
    const fetchMock = vi.fn().mockReturnValue(save);
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<ToastProvider><ProfileEditor {...base} profiles={{ world: { kind: "world", data: { name: "Old" } } }} /></ToastProvider>);
    await user.click(screen.getByRole("button", { name: /Lưu thế giới/ }));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    resolveSave(new Response(JSON.stringify({ state_version: 5, checkpoint_id: "cp" }), { status: 200 }));
    expect(await screen.findByRole("status")).toHaveTextContent("Đã lưu hồ sơ.");
  });

  it("keeps the edited draft after failure and clears the error after a successful retry", async () => {
    let resolveRetry!: (response: Response) => void;
    const retry = new Promise<Response>((resolve) => { resolveRetry = resolve; });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "failed" }), { status: 500 }))
      .mockReturnValueOnce(retry);
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<ToastProvider><ProfileEditor {...base} profiles={{ world: { kind: "world", data: { name: "Old" } } }} /></ToastProvider>);
    const input = screen.getByLabelText("Tên thế giới");
    await user.clear(input); await user.type(input, "Synthetic draft");
    await user.click(screen.getByRole("button", { name: /Lưu thế giới/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Không thể lưu");
    expect(input).toHaveValue("Synthetic draft");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Lưu thế giới/ }));
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    resolveRetry(new Response(JSON.stringify({ state_version: 5, checkpoint_id: "cp" }), { status: 200 }));
    expect(await screen.findByRole("status")).toHaveTextContent("Đã lưu hồ sơ.");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(input).toHaveValue("Synthetic draft");
  });

  it("preserves unknown profile keys and submits aliases as arrays with character identity", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ state_version: 5, checkpoint_id: "checkpoint-5" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<ProfileEditor {...base} profiles={{ world: { kind: "world", data: { name: "Lục địa", secret_rule: "keep" } }, persona: { kind: "persona", data: { name: "Linh" } }, "character:char-1": { kind: "character", data: { id: "char-1", name: "An", aliases: ["Bóng"], knowledge_scope: "known_by", known_by: ["char-2"] } } }} />);
    await user.click(screen.getByRole("button", { name: "Lưu thế giới" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const worldPayload = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    expect(worldPayload).toMatchObject({ branch_id: "branch-1", expected_state_version: 4, data: { name: "Lục địa", secret_rule: "keep" } });
    await user.clear(screen.getByLabelText("Bí danh An"));
    await user.type(screen.getByLabelText("Bí danh An"), "Bóng đêm, Người gác");
    await user.click(screen.getByRole("button", { name: "Lưu nhân vật An" }));
    const characterPayload = JSON.parse(fetchMock.mock.calls[1][1].body as string);
    expect(characterPayload.data).toMatchObject({ id: "char-1", aliases: ["Bóng đêm", "Người gác"], knowledge_scope: "known_by", known_by: ["char-2"] });
  });

  it("keeps a draft and refreshes the authoritative version on conflict", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "conflict" }), { status: 409 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ state_version: 9, checkpoint_id: "checkpoint-9" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<ProfileEditor {...base} profiles={{ world: { kind: "world", data: { name: "Cũ" } } }} />);
    const input = screen.getByLabelText("Tên thế giới");
    await user.clear(input); await user.type(input, "Bản nháp giữ lại");
    await user.click(screen.getByRole("button", { name: "Lưu thế giới" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Phiên bản đã thay đổi");
    expect(input).toHaveValue("Bản nháp giữ lại");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("exposes explicit style defaults and policy controls", () => {
    render(<ProfileEditor {...base} profiles={{ style: { kind: "style", data: { language: "vi", length: "medium", headings: false, emojis: false, viewpoint: "third_person", agency: "strict" } } }} />);
    expect(screen.getByLabelText("Ngôn ngữ style")).toHaveValue("vi");
    expect(screen.getByLabelText("Độ dài style")).toHaveValue("medium");
    expect(screen.getByLabelText("Tiêu đề style")).toBeInTheDocument();
    expect(screen.getByLabelText("Emoji style")).toBeInTheDocument();
    expect(screen.getByLabelText("Ngôi kể style")).toHaveValue("third_person");
    expect(screen.getByLabelText("Quy tắc agency")).toHaveTextContent("Player agency");
  });

  it("submits canonical style levels and never rewrites the fixed agency rule", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ state_version: 5, checkpoint_id: "cp" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<ProfileEditor {...base} profiles={{ style: { kind: "style", data: { language: "vi", length: "medium", heading_level: "low", emoji_level: "low", viewpoint: "third_person", agency_rule: "Player agency forbids invented speech/thought/choices." } } }} />);
    await user.click(screen.getByRole("button", { name: "Lưu style" }));
    const payload = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    expect(payload.data).toMatchObject({ heading_level: "low", emoji_level: "low", agency_rule: "Player agency forbids invented speech/thought/choices." });
    expect(payload.data).not.toHaveProperty("headings");
    expect(payload.data).not.toHaveProperty("emojis");
  });

  it("keeps audience controls out of character profile payloads", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ state_version: 5, checkpoint_id: "cp" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<ProfileEditor {...base} profiles={{ "character:char-1": { kind: "character", data: { id: "char-1", name: "An", aliases: [] } } }} />);
    expect(screen.queryByLabelText("Phạm vi kiến thức")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Lưu nhân vật An" }));
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string).data).not.toHaveProperty("knowledge_scope");
  });
});
