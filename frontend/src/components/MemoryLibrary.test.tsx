import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { MemoryLibrary } from "./MemoryLibrary";

describe("MemoryLibrary", () => {
  it("separates pending proposals and supports explicit review, provenance, source interval and retrieval", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([{ memory_id: "m1", id: "v1", version: 1, kind: "lore", text: "Canon", origin: "user", status: "approved", pinned: true, source_revision_ids: ["r1", "r2"], knowledge_scope: "public", known_by: [] }]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([{ memory_id: "m2", id: "v2", version: 1, kind: "event", text: "Đề xuất", origin: "ai", status: "pending", pinned: false, source_revision_ids: ["r3"], knowledge_scope: "public", known_by: [] }]), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryLibrary campaignId="campaign-1" branchId="branch-1" stateVersion={3} />);
    expect(await screen.findByText("Canon")).toBeInTheDocument();
    expect(screen.getByText("Đề xuất AI · Chờ duyệt")).toBeInTheDocument();
    expect(screen.getByText(/Nguồn revisions: r1, r2/)).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Duyệt đề xuất Đề xuất" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/approve"), expect.objectContaining({ method: "POST" })));
  });

  it("sends the selected retrieval policy with the current state version", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify([]), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<MemoryLibrary campaignId="campaign-1" branchId="branch-1" stateVersion={3} />);
    await screen.findByText("Chưa có ký ức đã duyệt");
    await user.selectOptions(screen.getByLabelText("Chính sách truy hồi"), "disabled");
    expect(JSON.parse(fetchMock.mock.calls.at(-1)![1].body as string)).toMatchObject({ branch_id: "branch-1", expected_state_version: 3, policy: "disabled" });
  });

  it("initializes retrieval policy from the persisted projection", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify([]), { status: 200 })));
    render(<MemoryLibrary campaignId="campaign-1" branchId="branch-1" stateVersion={3} retrievalPolicy="disabled" />);
    await screen.findByText("Chưa có ký ức đã duyệt");
    expect(screen.getByLabelText("Chính sách truy hồi")).toHaveValue("disabled");
  });

  it("sends memory audience and conflict fields and rejects reversed summary intervals", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify([]), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<MemoryLibrary campaignId="campaign-1" branchId="branch-1" stateVersion={3} sourceRevisionIds={["r1", "r2", "r3"]} />);
    await screen.findByText("Chưa có ký ức đã duyệt");
    await user.selectOptions(screen.getByLabelText("Loại"), "summary");
    await user.selectOptions(screen.getByLabelText("Revision bắt đầu"), "r3");
    await user.selectOptions(screen.getByLabelText("Revision kết thúc"), "r1");
    await user.type(screen.getByLabelText("Nội dung"), "Tóm tắt");
    await user.click(screen.getByRole("button", { name: "Thêm ký ức" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("liên tục");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await user.selectOptions(screen.getByLabelText("Revision bắt đầu"), "r1");
    await user.selectOptions(screen.getByLabelText("Revision kết thúc"), "r2");
    await user.selectOptions(screen.getByLabelText("Phạm vi kiến thức"), "known_by");
    await user.type(screen.getByLabelText("Nhân vật biết (UUID)"), "char-1");
    await user.type(screen.getByLabelText("Nhân vật liên quan (UUID)"), "char-2");
    await user.type(screen.getByLabelText("Chủ thể (UUID)"), "char-1");
    await user.type(screen.getByLabelText("Predicate"), "owns");
    await user.type(screen.getByLabelText("Giá trị"), "lantern");
    await user.click(screen.getByRole("button", { name: "Thêm ký ức" }));
    const payload = JSON.parse(fetchMock.mock.calls[2][1].body as string);
    expect(payload).toMatchObject({ source_revision_ids: ["r1", "r2"], knowledge_scope: "known_by", known_by: ["char-1"], entity_ids: ["char-2"], subject_id: "char-1", predicate: "owns", value: "lantern" });
  });

  it("retains every controlled edit field after 409 and retries with refreshed state", async () => {
    const conflict = vi.fn();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([{ memory_id: "m1", id: "v1", version: 1, kind: "canon", text: "Canon", origin: "user", status: "approved", pinned: false, source_revision_ids: ["r1"], knowledge_scope: "public", known_by: [], entity_ids: [], subject_id: null, predicate: null, value: null, object_id: null, supersedes_memory_id: null }]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "conflict" }), { status: 409 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ memory_id: "m1", id: "v2", version: 2, kind: "canon", text: "Đã sửa", origin: "user", status: "approved", pinned: false, source_revision_ids: ["r1"], knowledge_scope: "known_by", known_by: ["char-1"], entity_ids: ["char-2"], subject_id: "char-1", predicate: "owns", value: "lantern", object_id: "char-3", supersedes_memory_id: "m0" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const { rerender } = render(<MemoryLibrary campaignId="campaign-1" branchId="branch-1" stateVersion={3} onConflict={conflict} />);
    await screen.findByText("Canon");
    await user.click(screen.getByRole("button", { name: "Sửa Canon" }));
    await user.clear(screen.getByLabelText("Nội dung Canon")); await user.type(screen.getByLabelText("Nội dung Canon"), "Đã sửa");
    await user.selectOptions(screen.getByLabelText("Phạm vi Canon"), "known_by");
    await user.clear(screen.getByLabelText("Nhân vật biết Canon")); await user.type(screen.getByLabelText("Nhân vật biết Canon"), "char-1");
    await user.clear(screen.getByLabelText("Nhân vật liên quan Canon")); await user.type(screen.getByLabelText("Nhân vật liên quan Canon"), "char-2");
    await user.clear(screen.getByLabelText("Chủ thể Canon")); await user.type(screen.getByLabelText("Chủ thể Canon"), "char-1");
    await user.clear(screen.getByLabelText("Predicate Canon")); await user.type(screen.getByLabelText("Predicate Canon"), "owns");
    await user.clear(screen.getByLabelText("Giá trị Canon")); await user.type(screen.getByLabelText("Giá trị Canon"), "lantern");
    await user.clear(screen.getByLabelText("Đối tượng Canon")); await user.type(screen.getByLabelText("Đối tượng Canon"), "char-3");
    await user.clear(screen.getByLabelText("Thay thế Canon")); await user.type(screen.getByLabelText("Thay thế Canon"), "m0");
    await user.click(screen.getByRole("button", { name: "Lưu chỉnh sửa" }));
    expect(conflict).toHaveBeenCalled();
    expect(screen.getByLabelText("Nội dung Canon")).toHaveValue("Đã sửa");
    rerender(<MemoryLibrary campaignId="campaign-1" branchId="branch-1" stateVersion={4} onConflict={conflict} />);
    await user.click(screen.getByRole("button", { name: "Lưu chỉnh sửa" }));
    const payload = JSON.parse(fetchMock.mock.calls[3][1].body as string);
    expect(payload).toMatchObject({ expected_state_version: 4, text: "Đã sửa", known_by: ["char-1"], entity_ids: ["char-2"], subject_id: "char-1", predicate: "owns", value: "lantern", object_id: "char-3", supersedes_id: "m0" });
  });

  it("shows exact non-contiguous provenance and structured slot identity", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([{ memory_id: "memory-42", id: "v7", version: 7, kind: "canon", text: "Lantern", origin: "user", status: "approved", pinned: false, source_revision_ids: ["r1", "r3"], knowledge_scope: "known_by", known_by: ["char-1"], entity_ids: ["char-2"], subject_id: "char-1", predicate: "owns", value: "lantern", object_id: "char-3", supersedes_memory_id: "memory-9" }]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 })));
    render(<MemoryLibrary campaignId="campaign-1" branchId="branch-1" stateVersion={3} />);
    await screen.findByText("Lantern");
    expect(screen.getByText(/Nguồn revisions: r1, r3/)).toBeInTheDocument();
    expect(screen.getByText(/Memory ID: memory-42/)).toBeInTheDocument();
    expect(screen.getByText(/Predicate: owns/)).toBeInTheDocument();
    expect(screen.getByText(/Supersedes: memory-9/)).toBeInTheDocument();
  });
});
