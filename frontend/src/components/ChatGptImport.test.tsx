import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { readChatGptExportFiles } from "../features/import/readChatGptExportFiles";
import { ChatGptConversation } from "../features/import/parseChatGptExport";
import { ChatGptImport } from "./ChatGptImport";

vi.mock("../features/import/readChatGptExportFiles", () => ({
  readChatGptExportFiles: vi.fn(),
}));

const readFiles = vi.mocked(readChatGptExportFiles);

const conversation = (id: string, title = id): ChatGptConversation => ({
  id,
  title,
  current_node: "final",
  mapping: { final: { id: "final", message: null, parent: null } },
});

const preview = {
  conversation_id: "one",
  title: "one",
  turn_count: 1,
  skipped_messages: 0,
  warnings: [],
  sample_first: { action_text: "action", narrative_text: "narrative" },
  sample_last: { action_text: "action", narrative_text: "narrative" },
};

function renderImport(onImported = vi.fn()) {
  return render(<ChatGptImport onImported={onImported} onCancel={vi.fn()} />);
}

async function chooseFiles(files: File[]) {
  fireEvent.change(screen.getByLabelText("Tệp xuất từ ChatGPT"), { target: { files } });
  await waitFor(() => expect(readFiles).toHaveBeenCalled());
}

async function prepareImport(items = [conversation("one"), conversation("two")]) {
  readFiles.mockResolvedValue(items);
  const rendered = renderImport();
  await chooseFiles([new File(["zip"], "export.zip", { type: "application/zip" })]);
  vi.spyOn(api, "previewChatGptImport").mockResolvedValue(preview);
  await userEvent.setup().click(screen.getByRole("button", { name: /Xem tr/ }));
  await screen.findByText(/Tìm thấy/);
  await userEvent.setup().click(screen.getByRole("checkbox"));
  return rendered;
}

afterEach(() => {
  vi.restoreAllMocks();
  readFiles.mockReset();
});

describe("ChatGptImport", () => {
  it("passes ZIP files to the local reader", async () => {
    readFiles.mockResolvedValue([conversation("one")]);
    renderImport();
    const file = new File(["zip"], "export.zip", { type: "application/zip" });
    await chooseFiles([file]);
    expect(readFiles).toHaveBeenCalledWith([file]);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("posts only the conversation selected for preview and import", async () => {
    await prepareImport();
    const importSpy = vi.spyOn(api, "importChatGpt").mockResolvedValue({ campaign_id: "campaign", branch_id: "branch", checkpoint_id: "checkpoint", turn_count: 1, already_imported: false });
    await userEvent.setup().click(screen.getByRole("button", { name: /Nhập v/ }));
    await waitFor(() => expect(importSpy).toHaveBeenCalledTimes(1));
    expect(importSpy.mock.calls[0][0]).toEqual(conversation("one"));
  });

  it("clears preview and approval when switching conversations", async () => {
    await prepareImport();
    const select = screen.getByRole("combobox");
    await userEvent.setup().selectOptions(select, "1");
    expect(screen.queryByText(/Tìm thấy/)).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("does not start a second authorized import while one is pending", async () => {
    await prepareImport();
    let resolveImport: (value: { campaign_id: string; branch_id: string; checkpoint_id: string; turn_count: number; already_imported: boolean }) => void = () => undefined;
    const importSpy = vi.spyOn(api, "importChatGpt").mockReturnValue(new Promise((resolve) => { resolveImport = resolve; }));
    const button = screen.getByRole("button", { name: /Nhập v/ });
    await userEvent.setup().click(button);
    await userEvent.setup().click(button);
    expect(importSpy).toHaveBeenCalledTimes(1);
    resolveImport({ campaign_id: "campaign", branch_id: "branch", checkpoint_id: "checkpoint", turn_count: 1, already_imported: false });
  });

  it("ignores a stale preview error after switching conversations", async () => {
    readFiles.mockResolvedValue([conversation("one"), conversation("two")]);
    renderImport();
    await chooseFiles([new File(["json"], "conversations.json", { type: "application/json" })]);
    let rejectPreview: (reason?: unknown) => void = () => undefined;
    vi.spyOn(api, "previewChatGptImport").mockReturnValue(new Promise((_resolve, reject) => { rejectPreview = reject; }));
    await userEvent.setup().click(screen.getByRole("button", { name: /Xem tr/ }));
    await userEvent.setup().selectOptions(screen.getByRole("combobox"), "1");
    rejectPreview(new Error("stale preview"));
    await act(async () => undefined);
    expect(screen.queryByText("stale preview")).not.toBeInTheDocument();
  });

  it("ignores a completed import after unmount", async () => {
    const onImported = vi.fn();
    readFiles.mockResolvedValue([conversation("one"), conversation("two")]);
    const rendered = renderImport(onImported);
    await chooseFiles([new File(["zip"], "export.zip", { type: "application/zip" })]);
    vi.spyOn(api, "previewChatGptImport").mockResolvedValue(preview);
    await userEvent.setup().click(screen.getByRole("button", { name: /Xem tr/ }));
    await screen.findByText(/Tìm thấy/);
    await userEvent.setup().click(screen.getByRole("checkbox"));
    let resolveImport: (value: { campaign_id: string; branch_id: string; checkpoint_id: string; turn_count: number; already_imported: boolean }) => void = () => undefined;
    vi.spyOn(api, "importChatGpt").mockReturnValue(new Promise((resolve) => { resolveImport = resolve; }));
    await userEvent.setup().click(screen.getByRole("button", { name: /Nhập v/ }));
    rendered.unmount();
    resolveImport({ campaign_id: "campaign", branch_id: "branch", checkpoint_id: "checkpoint", turn_count: 1, already_imported: false });
    await act(async () => undefined);
    expect(onImported).not.toHaveBeenCalled();
  });
});
