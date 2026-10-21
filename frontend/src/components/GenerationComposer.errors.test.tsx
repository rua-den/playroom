import userEvent from "@testing-library/user-event";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { GenerationComposer } from "./GenerationComposer";
import type { CampaignProjection } from "../api/types";

const projection = { campaign: { id: "c", title: "Story", created_at: "", updated_at: "", archived_at: null }, branch: { id: "b", name: "main", state_version: 1, checkpoint_id: "cp" }, checkpoint: { id: "cp", state_version: 1, parent_checkpoint_id: null, selected_revision_ids: [], retrieval_policy: "auto" }, profiles: {}, scene: null, transcript: [], jobs: [] } as CampaignProjection;

describe("GenerationComposer provider validation messages", () => {
  beforeEach(() => { localStorage.clear(); sessionStorage.clear(); vi.restoreAllMocks(); });

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

  it("keeps unknown quota wording generic without Economy retry or cost CTA", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "preview", campaign_id: "c", branch_id: "b", checkpoint_id: "cp", action: "hello", status: "ready", profile_id: "p" }), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "quota schema secret" }), { status: 422 })));
    const user = userEvent.setup();
    render(<GenerationComposer ownerId="o" projection={projection} profileId="p" onCommitted={vi.fn()} onOpenCostSettings={vi.fn()} />);
    await user.type(screen.getByLabelText("Hành động tiếp theo"), "hello");
    await user.click(screen.getByRole("button", { name: "Gửi" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Không thể bắt đầu lượt kể chuyện; bản nháp vẫn được giữ.");
    expect(alert).not.toHaveTextContent("quota schema secret");
    expect(screen.queryByText(/Economy \+ Free only/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Mở Cài đặt chi phí" })).not.toBeInTheDocument();
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

  it("explains player-agency rejection and keeps the submitted action", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "preview", campaign_id: "c", branch_id: "b", checkpoint_id: "cp", action: "keep Henn mine", status: "ready", profile_id: "p" }), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        id: "job-agency", campaign_id: "c", branch_id: "b", checkpoint_id: "cp",
        status: "failed", mode: "economy", action: "keep Henn mine",
        draft: "", offset: 0, offset_unit: "utf16_code_units",
        failure: { code: "PLAYER_AGENCY_VIOLATION", message: "Narrator attempted to author the player persona" },
      }), { status: 201 })));
    const user = userEvent.setup();
    render(<GenerationComposer ownerId="o" projection={projection} profileId="p" onCommitted={vi.fn()} />);
    const input = screen.getByLabelText("Hành động tiếp theo");
    await user.type(input, "keep Henn mine");
    await user.click(screen.getByRole("button", { name: "Gửi" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("AI đã cố tự viết hành động");
    expect(alert).not.toHaveTextContent("Narrator attempted");
    expect(input).toHaveValue("keep Henn mine");
  });

  it("explains NPC knowledge rejection without exposing internal fact text", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "preview", campaign_id: "c", branch_id: "b", checkpoint_id: "cp", action: "ask Yuna", status: "ready", profile_id: "p" }), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        id: "job-knowledge", campaign_id: "c", branch_id: "b", checkpoint_id: "cp",
        status: "failed", mode: "economy", action: "ask Yuna",
        draft: "", offset: 0, offset_unit: "utf16_code_units",
        failure: { code: "NPC_KNOWLEDGE_VIOLATION", message: "B-17 private fact leaked" },
      }), { status: 201 })));
    const user = userEvent.setup();
    render(<GenerationComposer ownerId="o" projection={projection} profileId="p" onCommitted={vi.fn()} />);
    const input = screen.getByLabelText("Hành động tiếp theo");
    await user.type(input, "ask Yuna");
    await user.click(screen.getByRole("button", { name: "Gửi" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("NPC đã cố dùng thông tin");
    expect(alert).not.toHaveTextContent("B-17 private fact leaked");
    expect(input).toHaveValue("ask Yuna");
  });

  it("explains ungrounded precision rejection without leaking invented value", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "preview", campaign_id: "c", branch_id: "b", checkpoint_id: "cp", action: "continue", status: "ready", profile_id: "p" }), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        id: "job-grounding", campaign_id: "c", branch_id: "b", checkpoint_id: "cp",
        status: "failed", mode: "economy", action: "continue",
        draft: "", offset: 0, offset_unit: "utf16_code_units",
        failure: { code: "UNGROUNDED_PRECISION", message: "invented 17:12" },
      }), { status: 201 })));
    const user = userEvent.setup();
    render(<GenerationComposer ownerId="o" projection={projection} profileId="p" onCommitted={vi.fn()} />);
    const input = screen.getByLabelText("Hành động tiếp theo");
    await user.type(input, "continue");
    await user.click(screen.getByRole("button", { name: "Gửi" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("chi tiết thời gian chính xác");
    expect(alert).not.toHaveTextContent("17:12");
    expect(input).toHaveValue("continue");
  });

  it("keeps model switching available when only an interrupted historical job exists", () => {
    const onOpenModelSettings = vi.fn();
    render(<GenerationComposer ownerId="o" projection={{ ...projection, jobs: [{ id: "old", campaign_id: "c", branch_id: "b", checkpoint_id: "cp", status: "interrupted", mode: "economy", action: "old", created_at: "", cancel_requested: false }] }} profileId="p" onCommitted={vi.fn()} onOpenModelSettings={onOpenModelSettings} />);
    expect(screen.getByRole("button", { name: "Đổi model" })).toBeEnabled();
  });
});
