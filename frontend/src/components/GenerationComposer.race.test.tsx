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
    sessionStorage.clear();
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
    const intervals: Array<() => void> = [];
    const originalSetInterval = window.setInterval;
    vi.spyOn(window, "setInterval").mockImplementation((callback, delay) => {
      if (delay !== 1200) return originalSetInterval.call(window, callback, delay);
      intervals.push(callback as () => void);
      return setTimeout(() => undefined, 0);
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
      expect(intervals.length).toBeGreaterThan(0);
    });
    const poll = intervals[intervals.length - 1];
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

  it("keeps an exactly retyped fresh-send action through its first candidate poll", async () => {
    const current = projection("campaign-1", "branch-1", "checkpoint-1");
    const preview = { id: "preview-fresh", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", action: "Same action", status: "ready", profile_id: "profile-1" };
    const queued = { id: "job-fresh", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "queued", action: "Same action", draft: "", offset: 0, offset_unit: "utf16_code_units" };
    const candidate = { ...queued, status: "candidate", draft: "complete" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(preview), { status: 201 }))
      .mockResolvedValueOnce(response(queued as GenerationJob))
      .mockResolvedValueOnce(response(candidate as GenerationJob))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const intervals: Array<() => void> = [];
    const originalSetInterval = window.setInterval;
    vi.spyOn(window, "setInterval").mockImplementation((callback, delay) => {
      if (delay !== 1200) return originalSetInterval.call(window, callback, delay);
      intervals.push(callback as () => void);
      return setTimeout(() => undefined, 0);
    });
    const commitRefresh = deferred<CampaignProjection>();
    const onCommitted = vi.fn(() => commitRefresh.promise);
    render(<GenerationComposer ownerId="owner-1" projection={current} profileId="profile-1" onCommitted={onCommitted} />);
    const input = await screen.findByLabelText("Hành động tiếp theo");
    const user = userEvent.setup();
    await user.type(input, "Same action");
    await user.click(screen.getByRole("button", { name: "Gửi" }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2);
      expect(intervals.length).toBeGreaterThan(0);
    });
    await user.clear(input);
    await user.type(input, "Same action");
    expect(input).toHaveValue("Same action");

    await act(async () => { for (const callback of intervals) callback(); });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
    await waitFor(() => expect(onCommitted).toHaveBeenCalledOnce());
    await act(async () => { commitRefresh.resolve(current); });
    await waitFor(() => expect(input).toHaveValue("Same action"));
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/generate"))).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/commit"))).toHaveLength(1);
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

  it("rejects a retained old poll callback after switching campaign scope", async () => {
    const oldProjection = projection("campaign-old", "branch-old", "checkpoint-old");
    const newProjection = projection("campaign-new", "branch-new", "checkpoint-new");
    const oldSaved = identity("owner-1", "campaign-old", "branch-old", "Old action", "job-old");
    const newSaved = identity("owner-1", "campaign-new", "branch-new", "New action", "job-new");
    const oldKey = generationIdentityKey(oldSaved.ownerId, oldSaved.campaignId, oldSaved.branchId);
    const newKey = generationIdentityKey(newSaved.ownerId, newSaved.campaignId, newSaved.branchId);
    const oldRaw = JSON.stringify(oldSaved);
    const newRaw = JSON.stringify(newSaved);
    localStorage.setItem(oldKey, oldRaw);
    const oldCandidate = deferred<Response>();
    let oldJobRequests = 0;
    const fetchMock = vi.fn((url: string | URL) => {
      const target = String(url);
      if (target.includes("/events")) return Promise.resolve(new Response(JSON.stringify({ events: [] }), { status: 200 }));
      if (target.includes("job-old")) {
        oldJobRequests += 1;
        return oldJobRequests === 1
          ? Promise.resolve(response({ id: "job-old", campaign_id: "campaign-old", branch_id: "branch-old", checkpoint_id: "checkpoint-old", status: "running", action: "Old action" }))
          : oldCandidate.promise;
      }
      if (target.includes("job-new")) {
        return Promise.resolve(response({ id: "job-new", campaign_id: "campaign-new", branch_id: "branch-new", checkpoint_id: "checkpoint-new", status: "failed", action: "New action" }));
      }
      return Promise.resolve(new Response(JSON.stringify({ events: [] }), { status: 200 }));
    });
    vi.stubGlobal("fetch", fetchMock);
    const intervals: Array<() => void> = [];
    const originalSetInterval = window.setInterval;
    vi.spyOn(window, "setInterval").mockImplementation((callback, delay) => {
      if (delay !== 1200) return originalSetInterval.call(window, callback, delay);
      intervals.push(callback as () => void);
      return setTimeout(() => undefined, 0);
    });
    const onCommitted = vi.fn();
    const { rerender } = render(<GenerationComposer ownerId="owner-1" projection={oldProjection} profileId="profile-1" onCommitted={onCommitted} />);
    await waitFor(() => {
      expect(oldJobRequests).toBe(1);
      expect(intervals.length).toBeGreaterThan(0);
    });
    const stalePoll = intervals[intervals.length - 1];
    const oldRawAfterRecovery = localStorage.getItem(oldKey);

    localStorage.setItem(newKey, newRaw);
    rerender(<GenerationComposer ownerId="owner-1" projection={newProjection} profileId="profile-1" onCommitted={onCommitted} />);
    const input = await screen.findByLabelText("Hành động tiếp theo");
    await waitFor(() => expect(input).toHaveValue("New action"));
    const newRawAfterRecovery = localStorage.getItem(newKey);
    await act(async () => {
      stalePoll();
      await Promise.resolve();
    });
    if (oldJobRequests > 1) oldCandidate.resolve(response({ id: "job-old", campaign_id: "campaign-old", branch_id: "branch-old", checkpoint_id: "checkpoint-old", status: "candidate", action: "Old action", draft: "stale" }));
    await act(async () => { await Promise.resolve(); });

    expect(oldJobRequests).toBe(1);
    expect(input).toHaveValue("New action");
    expect(localStorage.getItem(oldKey)).toBe(oldRawAfterRecovery);
    expect(localStorage.getItem(newKey)).toBe(newRawAfterRecovery);
    expect(onCommitted).not.toHaveBeenCalled();
  });

  it("ignores a delayed cancel response after switching owner and campaign scope", async () => {
    const oldProjection = projection("campaign-old", "branch-old", "checkpoint-old");
    const newProjection = projection("campaign-new", "branch-new", "checkpoint-new");
    const cancelResponse = deferred<Response>();
    const fetchMock = vi.fn((url: string | URL, options?: RequestInit) => {
      const target = String(url);
      if (target.endsWith("/context/previews")) return Promise.resolve(new Response(JSON.stringify({ id: "preview-old", campaign_id: "campaign-old", branch_id: "branch-old", checkpoint_id: "checkpoint-old", action: "old action", status: "ready", profile_id: "profile-1" }), { status: 201 }));
      if (target.endsWith("/generate")) return Promise.resolve(response({ id: "job-old-cancel", campaign_id: "campaign-old", branch_id: "branch-old", checkpoint_id: "checkpoint-old", status: "running", action: "old action" }));
      if (target.endsWith("/cancel")) return cancelResponse.promise;
      if (target.includes("campaign-new")) return Promise.resolve(response({ id: "job-new", campaign_id: "campaign-new", branch_id: "branch-new", checkpoint_id: "checkpoint-new", status: "failed", action: "new action" }));
      return Promise.resolve(new Response(JSON.stringify({ events: [] }), { status: 200 }));
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const { rerender } = render(<GenerationComposer ownerId="owner-old" projection={oldProjection} profileId="profile-1" onCommitted={vi.fn()} />);
    const oldInput = screen.getByLabelText("Hành động tiếp theo");
    await user.type(oldInput, "old action");
    await user.click(screen.getByRole("button", { name: "Gửi" }));
    await user.click(await screen.findByRole("button", { name: "Dừng lượt kể" }));
    rerender(<GenerationComposer ownerId="owner-new" projection={newProjection} profileId="profile-1" onCommitted={vi.fn()} />);
    const newInput = screen.getByLabelText("Hành động tiếp theo");
    await user.type(newInput, "new draft");
    await act(async () => {
      cancelResponse.resolve(response({ id: "job-old-cancel", campaign_id: "campaign-old", branch_id: "branch-old", checkpoint_id: "checkpoint-old", status: "cancelled", action: "old action", draft: "old partial" }));
    });
    await waitFor(() => expect(newInput).toHaveValue("new draft"));
    expect(screen.queryByText("Đã dừng lượt kể; bản nháp vẫn được giữ.")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/generate"))).toHaveLength(1);
  });

  it("lets a same-job terminal poll win over a late cancel response", async () => {
    const current = projection("campaign-1", "branch-1", "checkpoint-1");
    const cancelResponse = deferred<Response>();
    const fetchMock = vi.fn((url: string | URL) => {
      const target = String(url);
      if (target.endsWith("/context/previews")) return Promise.resolve(new Response(JSON.stringify({ id: "preview-race", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", action: "keep draft", status: "ready", profile_id: "profile-1" }), { status: 201 }));
      if (target.endsWith("/generate")) return Promise.resolve(response({ id: "job-race", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "running", action: "keep draft", draft: "partial", offset: 7 }));
      if (target.endsWith("/cancel")) return cancelResponse.promise;
      if (target.endsWith("/jobs/job-race")) return Promise.resolve(response({ id: "job-race", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "cancelled", action: "keep draft", draft: "partial" }));
      return Promise.resolve(new Response(JSON.stringify({ events: [] }), { status: 200 }));
    });
    vi.stubGlobal("fetch", fetchMock);
    const intervals: Array<() => void> = [];
    const originalSetInterval = window.setInterval;
    vi.spyOn(window, "setInterval").mockImplementation((callback, delay) => {
      if (delay !== 1200) return originalSetInterval.call(window, callback, delay);
      intervals.push(callback as () => void);
      return setTimeout(() => undefined, 0);
    });
    const user = userEvent.setup();
    render(<GenerationComposer ownerId="owner-1" projection={current} profileId="profile-1" onCommitted={vi.fn()} />);
    const input = screen.getByLabelText("Hành động tiếp theo");
    await user.type(input, "keep draft");
    await user.click(screen.getByRole("button", { name: "Gửi" }));
    await waitFor(() => expect(intervals.length).toBeGreaterThan(0));
    await user.click(screen.getByRole("button", { name: "Dừng lượt kể" }));
    await act(async () => { intervals[0](); });
    expect(await screen.findByRole("status")).toHaveTextContent("Đã dừng lượt kể");
    cancelResponse.resolve(response({ id: "job-race", campaign_id: "campaign-1", branch_id: "branch-1", checkpoint_id: "checkpoint-1", status: "running", action: "keep draft", draft: "stale" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Đã dừng lượt kể"));
    expect(input).toHaveValue("keep draft");
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/generate"))).toHaveLength(1);
  });

  it("ignores a late cancel error after the same job is committed by polling", async () => {
    const current = projection("campaign-commit", "branch-commit", "checkpoint-commit");
    const cancelResponse = deferred<Response>();
    const fetchMock = vi.fn((url: string | URL) => {
      const target = String(url);
      if (target.endsWith("/context/previews")) return Promise.resolve(new Response(JSON.stringify({ id: "preview-commit", campaign_id: "campaign-commit", branch_id: "branch-commit", checkpoint_id: "checkpoint-commit", action: "commit this", status: "ready", profile_id: "profile-1" }), { status: 201 }));
      if (target.endsWith("/generate")) return Promise.resolve(response({ id: "job-commit", campaign_id: "campaign-commit", branch_id: "branch-commit", checkpoint_id: "checkpoint-commit", status: "running", action: "commit this" }));
      if (target.endsWith("/cancel")) return cancelResponse.promise;
      if (target.endsWith("/jobs/job-commit")) return Promise.resolve(response({ id: "job-commit", campaign_id: "campaign-commit", branch_id: "branch-commit", checkpoint_id: "checkpoint-commit", status: "committed", action: "commit this", draft: "complete" }));
      return Promise.resolve(new Response(JSON.stringify({ events: [] }), { status: 200 }));
    });
    vi.stubGlobal("fetch", fetchMock);
    const intervals: Array<() => void> = [];
    const originalSetInterval = window.setInterval;
    vi.spyOn(window, "setInterval").mockImplementation((callback, delay) => {
      if (delay !== 1200) return originalSetInterval.call(window, callback, delay);
      intervals.push(callback as () => void);
      return setTimeout(() => undefined, 0);
    });
    const onCommitted = vi.fn().mockResolvedValue(current);
    const user = userEvent.setup();
    render(<GenerationComposer ownerId="owner-1" projection={current} profileId="profile-1" onCommitted={onCommitted} />);
    await user.type(screen.getByLabelText("Hành động tiếp theo"), "commit this");
    await user.click(screen.getByRole("button", { name: "Gửi" }));
    await waitFor(() => expect(intervals.length).toBeGreaterThan(0));
    await user.click(screen.getByRole("button", { name: "Dừng lượt kể" }));
    await act(async () => { intervals[0](); });
    await waitFor(() => expect(onCommitted).toHaveBeenCalledOnce());
    cancelResponse.reject(new Error("late cancel failure"));
    await waitFor(() => expect(screen.queryByText("late cancel failure")).not.toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Dừng lượt kể" })).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/generate"))).toHaveLength(1);
  });
});
