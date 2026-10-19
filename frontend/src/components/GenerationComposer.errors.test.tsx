import userEvent from "@testing-library/user-event";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { GenerationComposer } from "./GenerationComposer";
import type { CampaignProjection } from "../api/types";

const projection = { campaign: { id: "c", title: "Story", created_at: "", updated_at: "", archived_at: null }, branch: { id: "b", name: "main", state_version: 1, checkpoint_id: "cp" }, checkpoint: { id: "cp", state_version: 1, parent_checkpoint_id: null, selected_revision_ids: [], retrieval_policy: "auto" }, profiles: {}, scene: null, transcript: [], jobs: [] } as CampaignProjection;

describe("GenerationComposer provider validation messages", () => {
  beforeEach(() => { localStorage.clear(); vi.restoreAllMocks(); });

  it("maps a paid Ollama Free only validation to an actionable message", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "preview", campaign_id: "c", branch_id: "b", checkpoint_id: "cp", action: "hello", status: "ready", profile_id: "p" }), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "free_only requires a verified free credential tier" }), { status: 422 })));
    const user = userEvent.setup();
    render(<GenerationComposer ownerId="o" projection={projection} profileId="p" onCommitted={vi.fn()} />);
    await user.type(screen.getByLabelText("Hành động tiếp theo"), "hello");
    await user.click(screen.getByRole("button", { name: "Gửi" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Free only đang chặn model trả phí");
    expect(screen.getByRole("alert")).not.toHaveTextContent("free_only requires");
  });

  it("offers cost settings directly from a rejected Send", async () => {
    const onOpenCostSettings = vi.fn();
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "preview", campaign_id: "c", branch_id: "b", checkpoint_id: "cp", action: "hello", status: "ready", profile_id: "p" }), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "free_only requires a verified free credential tier" }), { status: 422 })));
    const user = userEvent.setup();
    render(<GenerationComposer ownerId="o" projection={projection} profileId="p" onCommitted={vi.fn()} onOpenCostSettings={onOpenCostSettings} />);
    await user.type(screen.getByLabelText("Hành động tiếp theo"), "hello");
    await user.click(screen.getByRole("button", { name: "Gửi" }));
    await user.click(await screen.findByRole("button", { name: "Mở Cài đặt chi phí" }));
    expect(onOpenCostSettings).toHaveBeenCalledOnce();
  });

  it("sanitizes an unknown provider payload and keeps the draft", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "preview", campaign_id: "c", branch_id: "b", checkpoint_id: "cp", action: "keep me", status: "ready", profile_id: "p" }), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Chưa cấu hình hồ sơ nhà cung cấp Ollama included credit secret sk-secret" }), { status: 422 })));
    const user = userEvent.setup();
    render(<GenerationComposer ownerId="o" projection={projection} profileId="p" onCommitted={vi.fn()} />);
    const input = screen.getByLabelText("Hành động tiếp theo");
    await user.type(input, "keep me");
    await user.click(screen.getByRole("button", { name: "Gửi" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Không thể bắt đầu lượt kể chuyện; bản nháp vẫn được giữ."));
    expect(screen.getByRole("alert")).not.toHaveTextContent("sk-secret");
    expect(input).toHaveValue("keep me");
  });

  it("keeps model switching available when only an interrupted historical job exists", () => {
    const onOpenModelSettings = vi.fn();
    render(<GenerationComposer ownerId="o" projection={{ ...projection, jobs: [{ id: "old", campaign_id: "c", branch_id: "b", checkpoint_id: "cp", status: "interrupted", mode: "economy", action: "old", created_at: "", cancel_requested: false }] }} profileId="p" onCommitted={vi.fn()} onOpenModelSettings={onOpenModelSettings} />);
    expect(screen.getByRole("button", { name: "Đổi model" })).toBeEnabled();
  });
});
