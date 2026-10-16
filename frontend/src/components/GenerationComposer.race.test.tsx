import userEvent from "@testing-library/user-event";
import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { GenerationComposer, generationIdentityKey } from "./GenerationComposer";
import type { CampaignProjection, GenerationJob } from "../api/types";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}

function projection(campaignId: string, branchId: string, checkpointId: string): CampaignProjection {
  return {
    campaign: { id: campaignId, title: campaignId, created_at: "", updated_at: "", archived_at: null },
    branch: { id: branchId, name: "main", state_version: 1, checkpoint_id: checkpointId },
    checkpoint: { id: checkpointId, state_version: 1, parent_checkpoint_id: null, selected_revision_ids: [], retrieval_policy: "auto" },
    profiles: {}, scene: null, transcript: [], jobs: [],
  };
}

function identity(ownerId: string, campaignId: string, branchId: string, action: string, jobId: string) {
  return { ownerId, campaignId, branchId, checkpointId: `${campaignId}-checkpoint`, action, previewId: `${jobId}-preview`, idempotencyKey: `${jobId}-key`, jobId };
}

function response(job: Partial<GenerationJob> & Pick<GenerationJob, "id" | "campaign_id" | "branch_id" | "checkpoint_id" | "status">) {
  return new Response(JSON.stringify({ draft: "", offset: 0, offset_unit: "utf16_code_units", ...job }), { status: 200 });
}

describe("GenerationComposer stale async generation races", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("keeps an exactly retyped action after the delayed old commit truly settles", async () => {
    const current = projection("campaign-1", "branch-1", "checkpoint-1");
    const saved = identity("owner-1", "campaign-1", "branch-1", "Same action", "job-old");
    localStorage.setItem(generationIdentityKey(saved.ownerId, saved.campaignId, saved.branchId), JSON.stringify(saved));
    const candidate = { ...saved, id: saved.jobId, campaign_id: saved.campaignId, branch_id: saved.branchId, checkpoint_id: saved.checkpointId, status: "candidate", draft: "old draft", offset: 9, offset_unit: "utf16_code_units" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(candidate as GenerationJob))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const commitRefresh = deferred<CampaignProjection>();
    let refreshSettled = false;
    const onCommitted = vi.fn(async () => {
      const result = await commitRefresh.promise;
      refreshSettled = true;
      return result;
    });
    render(<GenerationComposer ownerId="owner-1" projection={current} profileId="profile-1" onCommitted={onCommitted} />);

    const input = await screen.findByLabelText("Hành động tiếp theo");
    await waitFor(() => expect(onCommitted).toHaveBeenCalledOnce());
    const user = userEvent.setup();
    await user.clear(input);
    await user.type(input, "Same action");
    expect(input).toHaveValue("Same action");

    await act(async () => { commitRefresh.resolve(current); });
    await waitFor(() => expect(refreshSettled).toBe(true));
    expect(input).toHaveValue("Same action");
  });

  it("keeps a draft edited while recovery is waiting for the old job response", async () => {
    const current = projection("campaign-1", "branch-1", "checkpoint-1");
    const saved = identity("owner-1", "campaign-1", "branch-1", "Old action", "job-old");
    localStorage.setItem(generationIdentityKey(saved.ownerId, saved.campaignId, saved.branchId), JSON.stringify(saved));
    const recovery = deferred<Response>();
    const commitRefresh = deferred<CampaignProjection>();
    const fetchMock = vi.fn()
      .mockImplementationOnce(() => recovery.promise)
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const onCommitted = vi.fn(() => commitRefresh.promise);
    render(<GenerationComposer ownerId="owner-1" projection={current} profileId="profile-1" onCommitted={onCommitted} />);

    const input = await screen.findByLabelText("Hành động tiếp theo");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
    const user = userEvent.setup();
    await user.clear(input);
    await user.type(input, "User draft");
    expect(input).toHaveValue("User draft");
    await act(async () => {
      recovery.resolve(response({ id: "job-old", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "candidate", action: "Old action", draft: "Old result" }));
    });
    await waitFor(() => expect(onCommitted).toHaveBeenCalledOnce());
    await act(async () => { commitRefresh.resolve(current); });
    await waitFor(() => expect(input).toHaveValue("User draft"));
  });

  it("keeps an exactly retyped action through a later running-job poll and commit", async () => {
    const current = projection("campaign-1", "branch-1", "checkpoint-1");
    const saved = identity("owner-1", "campaign-1", "branch-1", "Same action", "job-running");
    const durableKey = generationIdentityKey(saved.ownerId, saved.campaignId, saved.branchId);
    localStorage.setItem(durableKey, JSON.stringify(saved));
    const running = { id: saved.jobId, campaign_id: saved.campaignId, branch_id: saved.branchId, checkpoint_id: saved.checkpointId, status: "running", action: saved.action, draft: "partial", offset: 7, offset_unit: "utf16_code_units" };
    const candidate = { ...running, status: "candidate", draft: "complete" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(running as GenerationJob))
      .mockResolvedValueOnce(new Response(JSON.stringify({ events: [] }), { status: 200 }))
      .mockResolvedValueOnce(response(candidate as GenerationJob))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    let poll!: () => void;
    vi.spyOn(window, "setInterval").mockImplementation((callback) => {
      poll = callback as () => void;
      return 1;
    });
    const commitRefresh = deferred<CampaignProjection>();
    let refreshSettled = false;
    const onCommitted = vi.fn(async () => {
      const result = await commitRefresh.promise;
      refreshSettled = true;
      return result;
    });
    render(<GenerationComposer ownerId="owner-1" projection={current} profileId="profile-1" onCommitted={onCommitted} />);

    const input = await screen.findByLabelText("Hành động tiếp theo");
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2);
      expect(input).toHaveValue("Same action");
      expect(poll).toEqual(expect.any(Function));
    });
    const user = userEvent.setup();
    await user.clear(input);
    await user.type(input, "Same action");
    expect(input).toHaveValue("Same action");
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/generate")).length).toBe(0);

    await act(async () => { poll(); });
    await waitFor(() => expect(onCommitted).toHaveBeenCalledOnce());
    await act(async () => { commitRefresh.resolve(current); });
    await waitFor(() => expect(refreshSettled).toBe(true));
    expect(input).toHaveValue("Same action");
    expect(localStorage.getItem(durableKey)).toBeNull();
  });

  it("ignores a deferred old recovery after switching campaign while preserving both durable identities", async () => {
    const oldProjection = projection("campaign-old", "branch-old", "checkpoint-old");
    const newProjection = projection("campaign-new", "branch-new", "checkpoint-new");
    const oldSaved = identity("owner-1", "campaign-old", "branch-old", "Old action", "job-old");
    const newSaved = identity("owner-1", "campaign-new", "branch-new", "New action", "job-new");
    const oldKey = generationIdentityKey(oldSaved.ownerId, oldSaved.campaignId, oldSaved.branchId);
    const newKey = generationIdentityKey(newSaved.ownerId, newSaved.campaignId, newSaved.branchId);
    const oldRaw = JSON.stringify(oldSaved);
    const newRaw = JSON.stringify(newSaved);
    localStorage.setItem(oldKey, oldRaw);

    const oldRecovery = deferred<Response>();
    const newRecovery = deferred<Response>();
    const fetchMock = vi.fn((url: string | URL) => String(url).includes("job-old") ? oldRecovery.promise : newRecovery.promise);
    vi.stubGlobal("fetch", fetchMock);
    const onCommitted = vi.fn();
    const { rerender } = render(<GenerationComposer ownerId="owner-1" projection={oldProjection} profileId="profile-1" onCommitted={onCommitted} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());

    localStorage.setItem(newKey, newRaw);
    rerender(<GenerationComposer ownerId="owner-1" projection={newProjection} profileId="profile-1" onCommitted={onCommitted} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    await act(async () => {
      newRecovery.resolve(response({ id: "job-new", campaign_id: "campaign-new", branch_id: "branch-new", checkpoint_id: "checkpoint-new", status: "failed", action: "New action", failure: { code: "NEW_FAILURE" } }));
    });
    const input = await screen.findByLabelText("Hành động tiếp theo");
    await waitFor(() => expect(input).toHaveValue("New action"));
    const newRawAfterRecovery = localStorage.getItem(newKey);

    await act(async () => {
      oldRecovery.resolve(response({ id: "job-old", campaign_id: "campaign-old", branch_id: "branch-old", checkpoint_id: "checkpoint-old", status: "failed", action: "Old action", failure: { code: "OLD_FAILURE" } }));
    });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(input).toHaveValue("New action");
    expect(localStorage.getItem(oldKey)).toBe(oldRaw);
    expect(localStorage.getItem(newKey)).toBe(newRawAfterRecovery);
  });
});
