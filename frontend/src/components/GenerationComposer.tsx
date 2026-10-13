import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, ApiError } from "../api/client";
import type { CampaignProjection, ContextPreview, GenerationEvent, GenerationJob } from "../api/types";

export interface GenerationIdentity { ownerId: string; campaignId: string; branchId: string; checkpointId: string; action: string; previewId: string; idempotencyKey: string; jobId?: string; eventCursor?: number; mode?: string; policy?: string; cap?: string | null; }
export function generationIdentityKey(ownerId: string, campaignId: string, branchId: string) { return `playroom:generation:${ownerId}:${campaignId}:${branchId}`; }
export function mergeGenerationEvents(current: string, currentOffset: number, events: GenerationEvent[]) {
  let text = current; let offset = currentOffset; let gap = false;
  for (const event of events) {
    if (event.event_type !== "delta" && event.event_type !== "narration_delta") continue;
    if (event.offset <= offset) continue;
    if (event.offset !== offset + event.content.length) { gap = true; break; }
    text += event.content; offset = event.offset;
  }
  return { text, offset, gap };
}
function newKey() { return typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`; }
function recoverable(error: unknown) { return error instanceof TypeError || (error instanceof ApiError && error.status >= 500); }
function isQuota(error: unknown) { return error instanceof ApiError && (error.code === "QUOTA_EXCEEDED" || error.code === "UNSUPPORTED_SCHEMA" || error.code === "SCHEMA_INVALID" || error.code === "UNSUPPORTED_CAPABILITY" || /quota|schema|unsupported capability/i.test(error.message)); }
function isQuotaFailure(failure: GenerationJob["failure"]) { return Boolean(failure && (["QUOTA_EXCEEDED", "UNSUPPORTED_SCHEMA", "SCHEMA_INVALID", "UNSUPPORTED_CAPABILITY"].includes(failure.code ?? "") || /quota|schema|unsupported capability/i.test(failure.message ?? ""))); }

export function GenerationComposer({ ownerId, projection, profileId, onCommitted }: { ownerId: string; projection: CampaignProjection; profileId: string; onCommitted: () => Promise<CampaignProjection | void> | void }) {
  const [action, setAction] = useState(""); const [identity, setIdentity] = useState<GenerationIdentity | null>(null); const [preview, setPreview] = useState<ContextPreview | null>(null); const [job, setJob] = useState<GenerationJob | null>(null); const [draft, setDraft] = useState(""); const [error, setError] = useState<string | null>(null); const [economyRetry, setEconomyRetry] = useState(false); const [pending, setPending] = useState(false);

  const polling = useRef(false);
  const commitPromises = useRef(new Map<string, Promise<CampaignProjection | void>>());
  const committedJobs = useRef(new Set<string>());
  const draftDirty = useRef(false);
  const storageKey = generationIdentityKey(ownerId, projection.campaign.id, projection.branch.id);
  const persist = (value: GenerationIdentity) => { setIdentity(value); localStorage.setItem(storageKey, JSON.stringify(value)); };
  function commitCandidate(candidate: GenerationJob, saved: GenerationIdentity) {
    if (committedJobs.current.has(candidate.id)) return Promise.resolve();
    const existing = commitPromises.current.get(candidate.id);
    if (existing) return existing;
    const operation = (async () => {
      try {
        await api.commitGeneration(candidate.id);
        const refreshed = await onCommitted();
        committedJobs.current.add(candidate.id);
        localStorage.removeItem(storageKey);
        setIdentity(null);
        setJob(null);
        setDraft("");
        setAction("");
        setError(null);
        return refreshed;
      } catch (cause) {
        committedJobs.current.delete(candidate.id);
        persist({ ...saved, jobId: candidate.id });
        throw cause;
      }
    })();
    commitPromises.current.set(candidate.id, operation);
    void operation.finally(() => { if (commitPromises.current.get(candidate.id) === operation) commitPromises.current.delete(candidate.id); }).catch(() => undefined);
    return operation;
  }
  async function refresh(saved: GenerationIdentity) {
    const found = saved.jobId ? await api.getGenerationJob(saved.jobId) : await api.getGenerationByKey(saved.branchId, saved.idempotencyKey);
    if (found.status === "candidate" || found.status === "committed") draftDirty.current = false;
    let nextIdentity = { ...saved, jobId: found.id, eventCursor: saved.eventCursor ?? 0 };
    if (found.status === "committed") {
      setPending(true);
      try {
        await onCommitted();
        localStorage.removeItem(storageKey);
        setIdentity(null);
        setJob(null);
        setDraft("");
        setAction("");
      } finally { setPending(false); }
      return found;
    }
    if (found.status === "candidate") {
      setJob(found);
      if (!draftDirty.current) setDraft(found.draft ?? "");
      if (saved.action) setAction(saved.action); else if (found.action) setAction(found.action);
      setPending(true);
      try { await commitCandidate(found, nextIdentity); } catch { setError("Không thể lưu lượt kể hoàn chỉnh; hãy thử Gửi lại."); } finally { setPending(false); }
      return found;
    }
    if (["queued", "running", "cancelling"].includes(found.status)) {
      const stream = await api.getGenerationEvents(found.id, nextIdentity.eventCursor); const lastId = stream.events.reduce((max, event) => Math.max(max, event.id), nextIdentity.eventCursor ?? 0); nextIdentity = { ...nextIdentity, eventCursor: lastId };
      const merged = mergeGenerationEvents(found.draft ?? "", found.offset ?? 0, stream.events);
      if (merged.gap) { const authoritative = await api.getGenerationContent(found.id); setJob(authoritative); if (!draftDirty.current) setDraft(authoritative.draft ?? ""); } else if (merged.text !== (found.draft ?? "")) { setJob({ ...found, draft: merged.text, offset: merged.offset }); if (!draftDirty.current) setDraft(merged.text); } else { setJob(found); if (!draftDirty.current) setDraft(found.draft ?? ""); }
    } else { setJob(found); if (!draftDirty.current) setDraft(found.draft ?? ""); }
    if (saved.action) setAction(saved.action); else if (found.action) setAction(found.action);
    if (isQuotaFailure(found.failure)) { setEconomyRetry(true); setError("Nhà cung cấp không đáp ứng lượt này; bạn có thể thử economy miễn phí."); }
    if (nextIdentity.idempotencyKey) persist(nextIdentity); else setIdentity(nextIdentity);
    return found;
  }
  useEffect(() => {
    const raw = localStorage.getItem(storageKey);
    if (raw) { try { const saved = JSON.parse(raw) as GenerationIdentity; setIdentity(saved); if (saved.action) setAction(saved.action); void refresh(saved).catch(() => setError("Chưa thể khôi phục lượt kể; thông tin khôi phục vẫn được giữ lại.")); } catch { setError("Không thể đọc thông tin khôi phục lượt kể."); } return; }
    const recoverableJob = projection.jobs.find((candidate) => ["queued", "running", "cancelling", "interrupted", "candidate"].includes(candidate.status));
    if (recoverableJob) {
      const saved: GenerationIdentity = { ownerId, campaignId: projection.campaign.id, branchId: projection.branch.id, checkpointId: recoverableJob.checkpoint_id, action: recoverableJob.action ?? "", previewId: "", idempotencyKey: "", jobId: recoverableJob.id, eventCursor: 0, mode: recoverableJob.mode ?? undefined };
      void refresh(saved).catch(() => setError("Chưa thể khôi phục lượt kể; thông tin chiến dịch vẫn được giữ lại."));
    }
  }, [storageKey]);
  useEffect(() => { if (!identity?.jobId || !job || !["queued", "running", "cancelling"].includes(job.status)) return; const timer = window.setInterval(() => { if (polling.current) return; polling.current = true; void refresh(identity).catch(() => undefined).finally(() => { polling.current = false; }); }, 1200); return () => window.clearInterval(timer); }, [identity?.jobId, identity?.eventCursor, job?.status, storageKey]);
  async function startGeneration(nextProjection: CampaignProjection, retryMode?: "economy") {
    const nextAction = action; if (!nextAction.trim()) return;
    let selectedProfileId = profileId; let selectedMode: string | undefined = retryMode; let selectedPolicy: string | undefined = retryMode ? "free_only" : undefined; let selectedCap: string | null = retryMode ? null : null;
    if (!selectedProfileId) { const settings = await api.getProviderSettings(); const quality = !retryMode && settings.mode === "quality"; selectedProfileId = (quality ? settings.roles.context : settings.roles.narrator)?.id ?? ""; selectedMode = retryMode ?? settings.mode; selectedPolicy = retryMode ? "free_only" : settings.policy; selectedCap = retryMode ? null : settings.confirmed_usd_cap; if (!selectedProfileId) throw new Error("Chưa cấu hình hồ sơ nhà cung cấp cho vai trò kể chuyện."); }
    const nextPreview = await api.createContextPreview(nextProjection.campaign.id, { branch_id: nextProjection.branch.id, action: nextAction, profile_id: selectedProfileId }); setPreview(nextPreview);
    const saved: GenerationIdentity = { ownerId, campaignId: nextProjection.campaign.id, branchId: nextProjection.branch.id, checkpointId: nextPreview.checkpoint_id, action: nextAction, previewId: nextPreview.id, idempotencyKey: newKey(), eventCursor: 0, mode: selectedMode, policy: selectedPolicy, cap: selectedCap }; persist(saved);
    let nextJob: GenerationJob; try { nextJob = await api.generate(nextProjection.campaign.id, { branch_id: saved.branchId, action: saved.action, idempotency_key: saved.idempotencyKey, checkpoint_id: saved.checkpointId, preview_id: saved.previewId, mode: saved.mode, policy: saved.policy, cap: saved.cap }); } catch (cause) { if (isQuota(cause)) { localStorage.removeItem(storageKey); setIdentity(null); throw cause; } if (!recoverable(cause)) throw cause; try { nextJob = await api.getGenerationByKey(saved.branchId, saved.idempotencyKey); } catch (lookupError) { persist(saved); throw lookupError; } }
    const complete = { ...saved, jobId: nextJob.id }; persist(complete); draftDirty.current = false; setJob(nextJob); setDraft(nextJob.draft ?? "");
    if (nextJob.status === "candidate") { try { await commitCandidate(nextJob, complete); } catch (cause) { setError("Không thể lưu lượt kể hoàn chỉnh; hãy thử Gửi lại."); throw cause; } }
  }
  async function submit(event: FormEvent) { event.preventDefault(); if ((event.nativeEvent as SubmitEvent & { isComposing?: boolean }).isComposing || !action.trim() || pending) return; if (identity?.idempotencyKey && !job) { setError("Lượt kể trước chưa khôi phục được; hãy thử tải lại thay vì tạo lượt mới."); return; } if (job && ["queued", "running", "cancelling"].includes(job.status)) { setError("Lượt kể hiện tại vẫn đang chạy; hãy chờ hoặc hủy trước khi bắt đầu lượt mới."); return; } const retryMode = economyRetry ? "economy" as const : undefined; setPending(true); setError(null); setEconomyRetry(false); try { if (job?.status === "candidate") { await commitCandidate(job, identity ?? { ownerId, campaignId: projection.campaign.id, branchId: projection.branch.id, checkpointId: job.checkpoint_id, action, previewId: "", idempotencyKey: "" }); return; } await startGeneration(projection, retryMode); } catch (cause) { const quota = isQuota(cause); setEconomyRetry(quota); setError(cause instanceof ApiError && cause.status === 409 ? "Tác vụ đã thay đổi. Hãy tải lại chiến dịch." : cause instanceof Error && /Chưa cấu hình/.test(cause.message) ? cause.message : "Không thể bắt đầu lượt kể chuyện; bản nháp vẫn được giữ."); } finally { setPending(false); } }
  const stages = job?.cost_ledger?.stages ?? {};
  const active = Boolean(job && ["queued", "running", "cancelling"].includes(job.status));
  const busy = pending || active;
  return <section className="generation-composer" aria-label="Lượt kể chuyện"><form onSubmit={submit}><label htmlFor="generation-action">Lời và hành động tiếp theo</label><p className="composer-hint">Dùng **...** cho hành động hoặc suy nghĩ; văn bản thường là lời thoại.</p><textarea aria-label="Hành động tiếp theo" id="generation-action" className="touch-target" value={action} onChange={(event) => setAction(event.target.value)} onKeyDown={(event) => { if (event.key !== "Enter" || event.shiftKey) return; if (event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229) return; event.preventDefault(); event.currentTarget.form?.requestSubmit(); }} placeholder="Bạn muốn nói hoặc làm gì?" required /><button type="submit" className="primary-button touch-target" disabled={busy}>{busy ? "Đang gửi…" : "Gửi"}</button></form>{error && <div role="alert" className="form-error">{error}{economyRetry && <span> Lần Gửi tiếp theo sẽ thử economy miễn phí.</span>}</div>}{job && <details className="generation-details"><summary>Chi tiết lượt kể</summary><p>Giai đoạn: {job.status}</p>{preview && <p className="details-meta">Preview {preview.status}; checkpoint {preview.checkpoint_id}</p>}{job.attempt_counts_by_stage && <p className="details-meta">Số lượt theo phase: {Object.entries(job.attempt_counts_by_stage).map(([stage, counts]) => `${stage} ${Object.entries(counts).map(([phase, count]) => `${phase}:${count}`).join(",")}`).join(" · ")}</p>}{Object.entries(stages).map(([stage, ledger]) => <p className="details-meta" key={stage}>Chi phí {stage}: provider {ledger.provider_reported_cost_usd ?? "unknown"} · calculated {ledger.calculated_cost_usd ?? "unknown"} · estimated {ledger.estimated_cost_usd ?? "unknown"}</p>)}<textarea aria-label="Bản nháp kể chuyện" className="touch-target" value={draft} readOnly onChange={() => undefined} /></details>}</section>;
}
