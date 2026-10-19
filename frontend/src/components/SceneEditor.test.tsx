import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SceneEditor } from "./SceneEditor";
import { ToastProvider } from "./Toast";

describe("SceneEditor", () => {
  it("shows save success after acknowledgement and never for a local scene draft", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ focus_scene_id: null, scenes: [] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ state_version: 5, checkpoint_id: "cp" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<ToastProvider><SceneEditor campaignId="campaign-1" branchId="branch-1" stateVersion={4} /></ToastProvider>);
    await user.click(await screen.findByRole("button", { name: /Thêm cảnh/ }));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Lưu cảnh/ }));
    expect(await screen.findByRole("status")).toHaveTextContent("Đã lưu cảnh.");
  });

  it("translates API scene map to editable rows and puts list plus focus/presence ids", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ focus_scene_id: "scene-1", scenes: { "scene-1": { id: "scene-1", name: "Bến cảng", present_ids: ["char-1"] } } }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ state_version: 5, checkpoint_id: "checkpoint-5" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<SceneEditor campaignId="campaign-1" branchId="branch-1" stateVersion={4} />);
    expect(await screen.findByDisplayValue("Bến cảng")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Lưu cảnh" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const payload = JSON.parse(fetchMock.mock.calls[1][1].body as string);
    expect(payload).toMatchObject({ branch_id: "branch-1", expected_state_version: 4, scene_state: { focus_scene_id: "scene-1" } });
    expect(payload.scene_state.scenes).toEqual([{ id: "scene-1", name: "Bến cảng", present_ids: ["char-1"] }]);
  });

  it("adds scenes and edits character presence", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ focus_scene_id: null, scenes: [] }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<SceneEditor campaignId="campaign-1" branchId="branch-1" stateVersion={4} characters={[{ id: "char-1", name: "An" }]} />);
    await user.click(await screen.findByRole("button", { name: "Thêm cảnh" }));
    await user.type(screen.getByLabelText("Tên cảnh 1"), "Rừng");
    await user.click(screen.getByLabelText("An có mặt ở cảnh 1"));
    expect(screen.getByLabelText("An có mặt ở cảnh 1")).toBeChecked();
  });

  it("keeps scene draft on 409 and retries with refreshed state", async () => {
    const conflict = vi.fn();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ focus_scene_id: "scene-1", scenes: { "scene-1": { id: "scene-1", name: "Cũ", present_ids: [] } } }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "conflict" }), { status: 409 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ state_version: 5, checkpoint_id: "cp" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const { rerender } = render(<ToastProvider><SceneEditor campaignId="campaign-1" branchId="branch-1" stateVersion={4} onConflict={conflict} /></ToastProvider>);
    const input = await screen.findByDisplayValue("Cũ");
    await user.clear(input); await user.type(input, "Bản nháp cảnh"); await user.click(screen.getByRole("button", { name: "Lưu cảnh" }));
    expect(conflict).toHaveBeenCalled();
    expect(screen.getByDisplayValue("Bản nháp cảnh")).toBeInTheDocument();
    rerender(<ToastProvider><SceneEditor campaignId="campaign-1" branchId="branch-1" stateVersion={5} onConflict={conflict} /></ToastProvider>);
    await user.click(screen.getByRole("button", { name: "Lưu cảnh" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Đã lưu cảnh.");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(JSON.parse(fetchMock.mock.calls[2][1].body as string)).toMatchObject({ expected_state_version: 5, scene_state: { scenes: [{ name: "Bản nháp cảnh" }] } });
  });
});
