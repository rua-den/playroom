import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LegacyImport } from "./LegacyImport";
import { api } from "../api/client";

vi.mock("../api/client", () => ({
  ApiError: class ApiError extends Error {
    status = 400;
  },
  api: {
    previewLegacyImport: vi.fn(),
    importLegacyBundle: vi.fn(),
  },
}));

const preview = {
  format: "playroom_legacy_story_bundle",
  schema_version: "1.0.0",
  title: "Synthetic story",
  turn_count: 1,
  missing_history: true,
  counts: { characters: 1, canon_facts: 1, relationships: 0, timeline_events: 1, player_excerpts: 1 },
  checkpoint: { last_completed_chapter: 1, next_chapter: 2, next_chapter_written: false, present_character_count: 1 },
  warnings: [],
  requires_owner_review: true,
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function bundleFile(name: string) {
  return new File([JSON.stringify({ format: "playroom_legacy_story_bundle", campaign_create_payload: { title: name } })], `${name}.json`, { type: "application/json" });
}

function deferredBundleFile(name: string, text: ReturnType<typeof deferred<string>>) {
  const file = bundleFile(name);
  Object.defineProperty(file, "text", { value: () => text.promise });
  return file;
}

afterEach(() => vi.clearAllMocks());

describe("LegacyImport async ownership", () => {
  it("keeps the latest file when an earlier file finishes reading later", async () => {
    const firstText = deferred<string>();
    const secondText = deferred<string>();
    vi.mocked(api.previewLegacyImport).mockResolvedValue(preview);

    render(<StrictMode><LegacyImport onImported={vi.fn()} onCancel={vi.fn()} /></StrictMode>);
    const input = screen.getByLabelText(/Bundle JSON/i);
    const user = userEvent.setup();
    await user.upload(input, deferredBundleFile("first", firstText));
    await user.upload(input, deferredBundleFile("second", secondText));
    secondText.resolve(JSON.stringify({ format: "playroom_legacy_story_bundle", campaign_create_payload: { title: "second" } }));
    await waitFor(() => expect(screen.getByRole("button", { name: /Xem/i })).toBeEnabled());

    firstText.resolve(JSON.stringify({ format: "playroom_legacy_story_bundle", campaign_create_payload: { title: "first" } }));
    await Promise.resolve();
    await user.click(screen.getByRole("button", { name: /Xem/i }));
    await screen.findByRole("status");
    expect(vi.mocked(api.previewLegacyImport).mock.calls[0][0]).toMatchObject({ campaign_create_payload: { title: "second" } });
  });

  it("ignores a preview response and error belonging to a replaced file", async () => {
    const firstPreview = deferred<typeof preview>();
    const secondPreview = deferred<typeof preview>();
    vi.mocked(api.previewLegacyImport)
      .mockReturnValueOnce(firstPreview.promise)
      .mockReturnValueOnce(secondPreview.promise);

    render(<LegacyImport onImported={vi.fn()} onCancel={vi.fn()} />);
    const input = screen.getByLabelText(/Bundle JSON/i);
    const user = userEvent.setup();
    await user.upload(input, bundleFile("first"));
    await user.click(screen.getByRole("button", { name: /Xem/i }));
    await waitFor(() => expect(api.previewLegacyImport).toHaveBeenCalledTimes(1));

    await user.upload(input, bundleFile("second"));
    firstPreview.reject(new Error("stale preview failed"));
    await Promise.resolve();
    expect(screen.queryByRole("status")).toBeNull();

    await user.click(screen.getByRole("button", { name: /Xem/i }));
    await waitFor(() => expect(api.previewLegacyImport).toHaveBeenCalledTimes(2));
    secondPreview.resolve(preview);
    await screen.findByRole("status");
    expect(screen.getByRole("status")).toHaveTextContent("playroom_legacy_story_bundle");
  });

  it("does not notify the parent when an authorized import finishes after close", async () => {
    const importRequest = deferred<{ campaign_id: string; branch_id: string; checkpoint_id: string; turn_count: number; already_imported: boolean }>();
    vi.mocked(api.previewLegacyImport).mockResolvedValue(preview);
    vi.mocked(api.importLegacyBundle).mockReturnValue(importRequest.promise);
    const onImported = vi.fn();
    const { unmount } = render(<LegacyImport onImported={onImported} onCancel={vi.fn()} />);
    const user = userEvent.setup();
    const input = screen.getByLabelText(/Bundle JSON/i);
    await user.upload(input, bundleFile("authorized"));
    await user.click(screen.getByRole("button", { name: /Xem/i }));
    await screen.findByRole("status");
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: /Tạo chiến dịch/i }));
    await user.upload(input, bundleFile("replacement"));
    await user.click(screen.getByRole("button", { name: /Xem/i }));
    await screen.findByRole("status");
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: /Tạo chiến dịch/i }));
    expect(api.importLegacyBundle).toHaveBeenCalledTimes(1);
    unmount();

    importRequest.resolve({ campaign_id: "campaign-synthetic", branch_id: "branch-synthetic", checkpoint_id: "checkpoint-synthetic", turn_count: 1, already_imported: false });
    await Promise.resolve();
    await Promise.resolve();
    expect(onImported).not.toHaveBeenCalled();
  });
});
