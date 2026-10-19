import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, ApiError } from "../api/client";
import type {
  CampaignProjection,
  ContextPreview,
  GenerationEvent,
  GenerationJob,
} from "../api/types";

export interface GenerationIdentity {
  ownerId: string;
  campaignId: string;
  branchId: string;
  checkpointId: string;
  action: string;
  previewId: string;
  idempotencyKey: string;
  jobId?: string;
  eventCursor?: number;
  mode?: string;
  policy?: string;
  cap?: string | null;
}
interface GenerationOperationContext {
  epoch: number;
  action: string;
  actionRevision: number;
  storageKey: string;
}
export function generationIdentityKey(
  ownerId: string,
  campaignId: string,
  branchId: string,
) {
  return `playroom:generation:${ownerId}:${campaignId}:${branchId}`;
}
export function mergeGenerationEvents(
  current: string,
  currentOffset: number,
  events: GenerationEvent[],
) {
  let text = current;
  let offset = currentOffset;
  let gap = false;
  for (const event of events) {
    if (event.event_type !== "delta" && event.event_type !== "narration_delta")
      continue;
    if (event.offset <= offset) continue;
    if (event.offset !== offset + event.content.length) {
      gap = true;
      break;
    }
    text += event.content;
    offset = event.offset;
  }
  return { text, offset, gap };
}
function newKey() {
  return typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}
function recoverable(error: unknown) {
  return (
    error instanceof TypeError ||
    (error instanceof ApiError && error.status >= 500)
  );
}
function isQuota(error: unknown) {
  return (
    error instanceof ApiError &&
    (error.code === "QUOTA_EXCEEDED" ||
      error.code === "UNSUPPORTED_SCHEMA" ||
      error.code === "SCHEMA_INVALID" ||
      error.code === "UNSUPPORTED_CAPABILITY" ||
      /quota|schema|unsupported capability/i.test(error.message))
  );
}
function generationFailure(error: unknown): { message: string; economyRetry: boolean } {
  const raw = error instanceof ApiError ? `${error.code ?? ""} ${error.message}`.toLowerCase() : "";
  const validation = error instanceof ApiError && [400, 422].includes(error.status);
  if (validation && /free_only cannot exclude purchased-credit billing|cannot exclude purchased-credit billing/.test(raw))
    return { message: "Ollama chưa chứng minh được giới hạn chi phí cho profile này. Hãy mở Cài đặt chi phí và tự chấp thuận Capped paid trước khi gửi.", economyRetry: false };
  if (validation && /free_only|free only|verified free|credential tier/.test(raw))
    return { message: "Free only đang chặn model trả phí này. Hãy chọn profile Free đã xác minh hoặc mở Cài đặt chi phí để tự chấp thuận Capped paid.", economyRetry: false };
  if (validation && /ollama|purchased credit|included credit|spending authorization|requires.*grant/.test(raw))
    return { message: "Ollama chưa chứng minh được giới hạn chi phí cho profile này. Hãy mở Cài đặt chi phí và tự chấp thuận Capped paid trước khi gửi.", economyRetry: false };
  if (validation && /trial model|profile does not match|trial.*(missing|revoked|expired|mismatched)|active trial authorization|cumulative budget|job count exhausted|per-send cap/.test(raw))
    return { message: "Hạn mức trả phí chưa được chấp thuận cho đúng profile, đã hết hoặc vượt giới hạn lượt này. Hãy kiểm tra Cài đặt chi phí.", economyRetry: false };
  if (validation && /context budget|blocked context|input limit|requested output|token budget/.test(raw))
    return { message: "Context hoặc ngân sách lượt kể không đáp ứng model này. Hãy mở Cài đặt chi phí để xem giới hạn đã chấp thuận.", economyRetry: false };
  if (isQuota(error)) return { message: "Không thể gửi vì quota hoặc khả năng model không đáp ứng. Chỉ model được xác minh Free mới được gửi với Free only; bản nháp được giữ.", economyRetry: true };
  return { message: "Không thể bắt đầu lượt kể chuyện; bản nháp vẫn được giữ.", economyRetry: false };
}
function isQuotaFailure(failure: GenerationJob["failure"]) {
  return Boolean(
    failure &&
    ([
      "QUOTA_EXCEEDED",
      "UNSUPPORTED_SCHEMA",
      "SCHEMA_INVALID",
      "UNSUPPORTED_CAPABILITY",
    ].includes(failure.code ?? "") ||
      /quota|schema|unsupported capability/i.test(failure.message ?? "")),
  );
}

export function GenerationComposer({
  ownerId,
  projection,
  profileId,
  onCommitted,
  onOpenModelSettings,
  onOpenCostSettings,
  demoMode = false,
}: {
  ownerId: string;
  projection: CampaignProjection;
  profileId: string;
  onCommitted: () => Promise<CampaignProjection | void> | void;
  onOpenModelSettings?: () => void;
  onOpenCostSettings?: () => void;
  demoMode?: boolean;
}) {
  const [action, setAction] = useState("");
  const [identity, setIdentity] = useState<GenerationIdentity | null>(null);
  const [preview, setPreview] = useState<ContextPreview | null>(null);
  const [job, setJob] = useState<GenerationJob | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [economyRetry, setEconomyRetry] = useState(false);
  const [pending, setPending] = useState(false);

  const polling = useRef<number | null>(null);
  const operationEpoch = useRef(0);
  const scopeKeyRef = useRef("");
  const actionRevision = useRef(0);
  const commitPromises = useRef(
    new Map<string, Promise<CampaignProjection | void>>(),
  );
  const committedJobs = useRef(new Set<string>());
  const committedRefreshes = useRef(new Set<string>());
  const recoveryBaselines = useRef(
    new Map<string, { action: string; actionRevision: number }>(),
  );
  const recoveryStarted = useRef(new Set<string>());
  const unmountTimer = useRef<number | null>(null);
  const mountedRef = useRef(false);
  const draftDirty = useRef(false);
  const latestAction = useRef(action);
  latestAction.current = action;
  const isCurrentEpoch = (epoch: number) =>
    mountedRef.current && operationEpoch.current === epoch;
  const storageKey = generationIdentityKey(
    ownerId,
    projection.campaign.id,
    projection.branch.id,
  );
  const scopeKey = `${ownerId}:${projection.campaign.id}:${projection.branch.id}`;
  if (scopeKeyRef.current !== scopeKey) {
    scopeKeyRef.current = scopeKey;
    operationEpoch.current += 1;
  }
  const persist = (value: GenerationIdentity) => {
    setIdentity(value);
    localStorage.setItem(storageKey, JSON.stringify(value));
  };
  const persistInitial = (
    value: GenerationIdentity,
    context: GenerationOperationContext,
  ) => {
    localStorage.setItem(context.storageKey, JSON.stringify(value));
    if (isCurrentEpoch(context.epoch)) setIdentity(value);
  };
  const persistContext = (
    value: GenerationIdentity,
    context: GenerationOperationContext,
  ) => {
    const raw = localStorage.getItem(context.storageKey);
    if (!raw) return;
    try {
      if (
        (JSON.parse(raw) as GenerationIdentity).idempotencyKey !==
        value.idempotencyKey
      )
        return;
    } catch {
      return;
    }
    localStorage.setItem(context.storageKey, JSON.stringify(value));
    if (isCurrentEpoch(context.epoch)) setIdentity(value);
  };
  // A definitive pre-reservation rejection may release only its own durable
  // identity. Never clear a newer request or an ambiguous provider dispatch.
  const releaseRejected = (
    saved: GenerationIdentity,
    context?: GenerationOperationContext,
  ) => {
    const targetKey = context?.storageKey ?? storageKey;
    const raw = localStorage.getItem(targetKey);
    if (!raw) return;
    try {
      if (
        (JSON.parse(raw) as GenerationIdentity).idempotencyKey !==
        saved.idempotencyKey
      )
        return;
    } catch {
      return;
    }
    localStorage.removeItem(targetKey);
    if (!context || isCurrentEpoch(context.epoch))
      setIdentity((current) =>
        current?.idempotencyKey === saved.idempotencyKey ? null : current,
      );
  };
  function commitCandidate(
    candidate: GenerationJob,
    saved: GenerationIdentity,
    context?: GenerationOperationContext,
  ) {
    if (committedJobs.current.has(candidate.id)) return Promise.resolve();
    const existing = commitPromises.current.get(candidate.id);
    if (existing) return existing;
    const operationContext = context ?? {
      epoch: operationEpoch.current,
      action: latestAction.current,
      actionRevision: actionRevision.current,
      storageKey,
    };
    const candidateEpoch = operationContext.epoch;
    const actionAtStart = operationContext.action;
    const actionRevisionAtStart = operationContext.actionRevision;
    const operation = (async () => {
      try {
        await api.commitGeneration(candidate.id);
        const refreshed = await onCommitted();
        if (!refreshed)
          throw new Error(
            "Committed turn has not been refreshed in the campaign",
          );
        if (!isCurrentEpoch(candidateEpoch)) return refreshed;
        committedJobs.current.add(candidate.id);
        const raw = localStorage.getItem(operationContext.storageKey);
        if (raw) {
          try {
            if (
              (JSON.parse(raw) as GenerationIdentity).idempotencyKey ===
              saved.idempotencyKey
            )
              localStorage.removeItem(operationContext.storageKey);
          } catch {
            /* keep the durable receipt */
          }
        }
        setIdentity(null);
        setJob(null);
        setDraft("");
        if (
          actionRevision.current === actionRevisionAtStart &&
          latestAction.current === actionAtStart
        )
          setAction("");
        setError(null);
        return refreshed;
      } catch (cause) {
        committedJobs.current.delete(candidate.id);
        persistContext({ ...saved, jobId: candidate.id }, operationContext);
        throw cause;
      }
    })();
    commitPromises.current.set(candidate.id, operation);
    void operation
      .finally(() => {
        if (commitPromises.current.get(candidate.id) === operation)
          commitPromises.current.delete(candidate.id);
      })
      .catch(() => undefined);
    return operation;
  }
  async function refresh(saved: GenerationIdentity) {
    const refreshEpoch = operationEpoch.current;
    const refreshStorageKey = generationIdentityKey(
      saved.ownerId,
      saved.campaignId,
      saved.branchId,
    );
    const baselineKey =
      saved.idempotencyKey || saved.jobId || refreshStorageKey;
    const baseline = recoveryBaselines.current.get(baselineKey) ?? {
      action: saved.action || latestAction.current,
      actionRevision: actionRevision.current,
    };
    recoveryBaselines.current.set(baselineKey, baseline);
    const actionAtStart = baseline.action;
    const actionRevisionAtStart = baseline.actionRevision;
    const found = saved.jobId
      ? await api.getGenerationJob(saved.jobId)
      : await api.getGenerationByKey(saved.branchId, saved.idempotencyKey);
    if (!isCurrentEpoch(refreshEpoch)) return found;
    if (found.status === "candidate" || found.status === "committed")
      draftDirty.current = false;
    let nextIdentity = {
      ...saved,
      jobId: found.id,
      eventCursor: saved.eventCursor ?? 0,
    };
    if (found.status === "committed") {
      if (!isCurrentEpoch(refreshEpoch)) return found;
      if (committedRefreshes.current.has(found.id)) return found;
      committedRefreshes.current.add(found.id);
      setPending(true);
      let refreshedSuccessfully = false;
      try {
        const refreshed = await onCommitted();
        if (!isCurrentEpoch(refreshEpoch)) return found;
        if (!refreshed)
          throw new Error(
            "Committed turn has not been refreshed in the campaign",
          );
        const raw = localStorage.getItem(refreshStorageKey);
        if (raw) {
          try {
            if (
              (JSON.parse(raw) as GenerationIdentity).idempotencyKey ===
              nextIdentity.idempotencyKey
            )
              localStorage.removeItem(refreshStorageKey);
          } catch {
            /* keep the durable receipt */
          }
        }
        setIdentity(null);
        setJob(null);
        setDraft("");
        if (
          actionRevision.current === actionRevisionAtStart &&
          latestAction.current === actionAtStart
        )
          setAction("");
        refreshedSuccessfully = true;
      } finally {
        if (isCurrentEpoch(refreshEpoch)) setPending(false);
        if (!refreshedSuccessfully) committedRefreshes.current.delete(found.id);
      }
      return found;
    }
    if (found.status === "candidate") {
      if (!isCurrentEpoch(refreshEpoch)) return found;
      setJob(found);
      if (!draftDirty.current) setDraft(found.draft ?? "");
      if (
        actionRevision.current === actionRevisionAtStart &&
        (saved.action || found.action)
      )
        setAction(saved.action || found.action || "");
      setPending(true);
      try {
        await commitCandidate(found, nextIdentity, {
          epoch: refreshEpoch,
          action: actionAtStart,
          actionRevision: actionRevisionAtStart,
          storageKey: refreshStorageKey,
        });
      } catch {
        if (isCurrentEpoch(refreshEpoch))
          setError("Không thể lưu lượt kể hoàn chỉnh; hãy thử Gửi lại.");
      } finally {
        if (isCurrentEpoch(refreshEpoch)) setPending(false);
      }
      return found;
    }
    if (["queued", "running", "cancelling"].includes(found.status)) {
      if (!isCurrentEpoch(refreshEpoch)) return found;
      const stream = await api.getGenerationEvents(
        found.id,
        nextIdentity.eventCursor,
      );
      const lastId = stream.events.reduce(
        (max, event) => Math.max(max, event.id),
        nextIdentity.eventCursor ?? 0,
      );
      nextIdentity = { ...nextIdentity, eventCursor: lastId };
      if (!isCurrentEpoch(refreshEpoch)) return found;
      const merged = mergeGenerationEvents(
        found.draft ?? "",
        found.offset ?? 0,
        stream.events,
      );
      if (merged.gap) {
        const authoritative = await api.getGenerationContent(found.id);
        if (!isCurrentEpoch(refreshEpoch)) return found;
        setJob(authoritative);
        if (!draftDirty.current) setDraft(authoritative.draft ?? "");
      } else if (merged.text !== (found.draft ?? "")) {
        setJob({ ...found, draft: merged.text, offset: merged.offset });
        if (!draftDirty.current) setDraft(merged.text);
      } else {
        setJob(found);
        if (!draftDirty.current) setDraft(found.draft ?? "");
      }
    } else {
      setJob(found);
      if (!draftDirty.current) setDraft(found.draft ?? "");
    }
    if (
      actionRevision.current === actionRevisionAtStart &&
      (saved.action || found.action)
    )
      setAction(saved.action || found.action || "");
    if (isQuotaFailure(found.failure)) {
      setEconomyRetry(true);
      setError(
        "Nhà cung cấp đã từ chối lượt này. Có thể thử Economy + Free only, nhưng chỉ model được xác minh Free mới được gửi.",
      );
    }
    if (!isCurrentEpoch(refreshEpoch)) return found;
    if (nextIdentity.idempotencyKey) persist(nextIdentity);
    else setIdentity(nextIdentity);
    return found;
  }
  useEffect(() => {
    mountedRef.current = true;
    if (unmountTimer.current !== null) {
      window.clearTimeout(unmountTimer.current);
      unmountTimer.current = null;
    }
    return () => {
      mountedRef.current = false;
      unmountTimer.current = window.setTimeout(() => {
        operationEpoch.current += 1;
        unmountTimer.current = null;
      }, 0);
    };
  }, []);
  useEffect(() => {
    const raw = localStorage.getItem(storageKey);
    if (raw) {
      if (recoveryStarted.current.has(storageKey)) return;
      recoveryStarted.current.add(storageKey);
      try {
        const saved = JSON.parse(raw) as GenerationIdentity;
        setIdentity(saved);
        if (saved.action) setAction(saved.action);
        const recoveryEpoch = operationEpoch.current;
        void refresh(saved).catch(() => {
          if (isCurrentEpoch(recoveryEpoch))
            setError(
              "Chưa thể khôi phục lượt kể; thông tin khôi phục vẫn được giữ lại.",
            );
        });
      } catch {
        setError("Không thể đọc thông tin khôi phục lượt kể.");
      }
      return;
    }
    const recoverableJob = projection.jobs.find((candidate) =>
      ["queued", "running", "cancelling", "interrupted", "candidate"].includes(
        candidate.status,
      ),
    );
    if (recoverableJob) {
      if (recoveryStarted.current.has(storageKey)) return;
      recoveryStarted.current.add(storageKey);
      const saved: GenerationIdentity = {
        ownerId,
        campaignId: projection.campaign.id,
        branchId: projection.branch.id,
        checkpointId: recoverableJob.checkpoint_id,
        action: recoverableJob.action ?? "",
        previewId: "",
        idempotencyKey: "",
        jobId: recoverableJob.id,
        eventCursor: 0,
        mode: recoverableJob.mode ?? undefined,
      };
      const recoveryEpoch = operationEpoch.current;
      void refresh(saved).catch(() => {
        if (isCurrentEpoch(recoveryEpoch))
          setError(
            "Chưa thể khôi phục lượt kể; thông tin chiến dịch vẫn được giữ lại.",
          );
      });
    }
  }, [storageKey]);
  useEffect(() => {
    if (
      !identity?.jobId ||
      !job ||
      identity.ownerId !== ownerId ||
      identity.campaignId !== projection.campaign.id ||
      identity.branchId !== projection.branch.id ||
      !["queued", "running", "cancelling"].includes(job.status)
    )
      return;
    const effectEpoch = operationEpoch.current;
    const effectScopeKey = scopeKey;
    const timer = window.setInterval(() => {
      if (
        !isCurrentEpoch(effectEpoch) ||
        scopeKeyRef.current !== effectScopeKey
      )
        return;
      if (polling.current === effectEpoch) return;
      polling.current = effectEpoch;
      void refresh(identity)
        .catch(() => undefined)
        .finally(() => {
          if (polling.current === effectEpoch) polling.current = null;
        });
    }, 1200);
    return () => window.clearInterval(timer);
  }, [identity?.jobId, identity?.eventCursor, job?.status, storageKey]);
  async function startGeneration(
    nextProjection: CampaignProjection,
    retryMode: "economy" | undefined,
    context: GenerationOperationContext = {
      epoch: operationEpoch.current,
      action: action,
      actionRevision: actionRevision.current,
      storageKey,
    },
  ) {
    const nextAction = context.action;
    if (!nextAction.trim()) return;
    let selectedProfileId = profileId;
    let selectedMode: string | undefined = retryMode;
    let selectedPolicy: string | undefined = retryMode
      ? "free_only"
      : undefined;
    let selectedCap: string | null = retryMode ? null : null;
    if (!selectedProfileId) {
      const settings = await api.getProviderSettings();
      if (!isCurrentEpoch(context.epoch)) return;
      const quality = !retryMode && settings.mode === "quality";
      selectedProfileId =
        (quality ? settings.roles.context : settings.roles.narrator)?.id ?? "";
      selectedMode = retryMode ?? settings.mode;
      selectedPolicy = retryMode ? "free_only" : settings.policy;
      selectedCap = retryMode ? null : settings.confirmed_usd_cap;
      if (!selectedProfileId)
        throw new Error(
          "Chưa cấu hình hồ sơ nhà cung cấp cho vai trò kể chuyện.",
        );
    }
    const nextPreview = await api.createContextPreview(
      nextProjection.campaign.id,
      {
        branch_id: nextProjection.branch.id,
        action: nextAction,
        profile_id: selectedProfileId,
      },
    );
    if (!isCurrentEpoch(context.epoch)) return;
    setPreview(nextPreview);
    const saved: GenerationIdentity = {
      ownerId,
      campaignId: nextProjection.campaign.id,
      branchId: nextProjection.branch.id,
      checkpointId: nextPreview.checkpoint_id,
      action: nextAction,
      previewId: nextPreview.id,
      idempotencyKey: newKey(),
      eventCursor: 0,
      mode: selectedMode,
      policy: selectedPolicy,
      cap: selectedCap,
    };
    recoveryBaselines.current.set(saved.idempotencyKey, {
      action: context.action,
      actionRevision: context.actionRevision,
    });
    persistInitial(saved, context);
    let nextJob: GenerationJob;
    try {
      nextJob = await api.generate(nextProjection.campaign.id, {
        branch_id: saved.branchId,
        action: saved.action,
        idempotency_key: saved.idempotencyKey,
        checkpoint_id: saved.checkpointId,
        preview_id: saved.previewId,
        mode: saved.mode,
        policy: saved.policy,
        cap: saved.cap,
      });
    } catch (cause) {
      if (
        cause instanceof ApiError &&
        [400, 401, 403, 404, 422, 429].includes(cause.status)
      ) {
        // An acknowledged FastAPI rejection: no generation job was reserved.
        // A 5xx remains uncertain even when its error text mentions quota/schema.
        releaseRejected(saved, context);
        throw cause;
      }
      if (cause instanceof ApiError && cause.status === 409) {
        // A conflict might be a stale checkpoint, but could also be an
        // existing idempotency key. Resolve it before releasing anything.
        try {
          nextJob = await api.getGenerationByKey(
            saved.branchId,
            saved.idempotencyKey,
          );
          // A conflicting idempotency payload may resolve to a *different*
          // submitted action; never adopt or auto-commit that foreign job.
          if (
            nextJob.branch_id !== saved.branchId ||
            nextJob.checkpoint_id !== saved.checkpointId ||
            nextJob.action !== saved.action
          ) {
            persistContext(saved, context);
            throw cause;
          }
        } catch (lookupError) {
          if (lookupError instanceof ApiError && lookupError.status === 404) {
            // The explicit conflict and authoritative missing-key response
            // together establish that no job was reserved under this key.
            releaseRejected(saved, context);
            if (isCurrentEpoch(context.epoch)) await onCommitted();
            throw cause;
          }
          persistContext(saved, context);
          throw lookupError;
        }
      } else {
        if (!recoverable(cause)) throw cause;
        try {
          nextJob = await api.getGenerationByKey(
            saved.branchId,
            saved.idempotencyKey,
          );
        } catch (lookupError) {
          persistContext(saved, context);
          throw lookupError;
        }
      }
    }
    const complete = { ...saved, jobId: nextJob.id };
    persistContext(complete, context);
    if (!isCurrentEpoch(context.epoch)) {
      if (nextJob.status === "candidate")
        await commitCandidate(nextJob, complete, context);
      return;
    }
    draftDirty.current = false;
    setJob(nextJob);
    setDraft(nextJob.draft ?? "");
    if (nextJob.status === "candidate") {
      try {
        await commitCandidate(nextJob, complete, context);
      } catch (cause) {
        if (isCurrentEpoch(context.epoch))
          setError("Không thể lưu lượt kể hoàn chỉnh; hãy thử Gửi lại.");
        throw cause;
      }
    }
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (
      (event.nativeEvent as SubmitEvent & { isComposing?: boolean })
        .isComposing ||
      !action.trim() ||
      pending
    )
      return;
    if (identity?.idempotencyKey && !job) {
      setError(
        "Lượt kể trước chưa khôi phục được; hãy thử tải lại thay vì tạo lượt mới.",
      );
      return;
    }
    if (job && ["queued", "running", "cancelling"].includes(job.status)) {
      setError(
        "Lượt kể hiện tại vẫn đang chạy; hãy chờ hoặc hủy trước khi bắt đầu lượt mới.",
      );
      return;
    }
    operationEpoch.current += 1;
    const submitEpoch = operationEpoch.current;
    const submitContext: GenerationOperationContext = {
      epoch: submitEpoch,
      action,
      actionRevision: actionRevision.current,
      storageKey,
    };
    const retryMode = economyRetry ? ("economy" as const) : undefined;
    setPending(true);
    setError(null);
    setEconomyRetry(false);
    try {
      if (job?.status === "candidate") {
        await commitCandidate(
          job,
          identity ?? {
            ownerId,
            campaignId: projection.campaign.id,
            branchId: projection.branch.id,
            checkpointId: job.checkpoint_id,
            action,
            previewId: "",
            idempotencyKey: "",
          },
          submitContext,
        );
        return;
      }
      await startGeneration(projection, retryMode, submitContext);
    } catch (cause) {
      if (!isCurrentEpoch(submitEpoch)) return;
      const failure = generationFailure(cause);
      setEconomyRetry(failure.economyRetry);
      const missingConfiguration = cause instanceof Error && cause.message === "Chưa cấu hình hồ sơ nhà cung cấp cho vai trò kể chuyện.";
      setError(cause instanceof ApiError && cause.status === 409
        ? "Tác vụ đã thay đổi. Hãy tải lại chiến dịch."
        : missingConfiguration ? cause.message : failure.message);
    } finally {
      if (isCurrentEpoch(submitEpoch)) setPending(false);
    }
  }
  const stages = job?.cost_ledger?.stages ?? {};
  const active = Boolean(
    job && ["queued", "running", "cancelling"].includes(job.status),
  );
  const busy = pending || active;
  const modelBlocked = busy || job?.status === "candidate" || Boolean(identity?.idempotencyKey && !job);
  return (
    <section className="generation-composer" aria-label="Lượt kể chuyện">
      {demoMode && (
        <div className="demo-runtime-notice composer-runtime-notice" role="status" aria-label="Chế độ demo tổng hợp">
          <strong>Chế độ demo tổng hợp</strong>
          <span>Phản hồi mẫu có thể lặp lại; demo không gọi AI thật dù bạn đổi model.</span>
        </div>
      )}
      <form onSubmit={submit}>
        <label htmlFor="generation-action">Lời và hành động tiếp theo</label>
        <p className="composer-hint">
          Dùng **...** cho hành động hoặc suy nghĩ; văn bản thường là lời thoại.
        </p>
        <textarea
          aria-label="Hành động tiếp theo"
          id="generation-action"
          className="touch-target"
          value={action}
          onChange={(event) => {
            actionRevision.current += 1;
            setAction(event.target.value);
          }}
          onKeyDown={(event) => {
            if (event.key !== "Enter" || event.shiftKey) return;
            if (
              event.nativeEvent.isComposing ||
              event.nativeEvent.keyCode === 229
            )
              return;
            event.preventDefault();
            event.currentTarget.form?.requestSubmit();
          }}
          placeholder="Bạn muốn nói hoặc làm gì?"
          required
        />
        <div className="composer-actions">
        <button
          type="submit"
          className="primary-button touch-target"
          disabled={busy}
        >
          {busy ? "Đang gửi…" : "Gửi"}
        </button>
        {onOpenModelSettings && (
          <button type="button" className="quiet-button touch-target" onClick={onOpenModelSettings} disabled={modelBlocked}>
            Đổi model
          </button>
        )}
        </div>
      </form>
      {error && (
        <div role="alert" className="form-error">
          {error}
          {economyRetry && (
            <span>
              {" "}
              Lần Gửi tiếp theo sẽ dùng Economy + Free only; đây không phải hạn
              mức lượt miễn phí của Ollama.
            </span>
          )}
          {onOpenCostSettings && <button type="button" className="quiet-button touch-target composer-error-settings" onClick={onOpenCostSettings}>Mở Cài đặt chi phí</button>}
        </div>
      )}
      {job && (
        <details className="generation-details">
          <summary>Chi tiết lượt kể</summary>
          <p>Giai đoạn: {job.status}</p>
          {preview && (
            <p className="details-meta">
              Preview {preview.status}; checkpoint {preview.checkpoint_id}
            </p>
          )}
          {job.attempt_counts_by_stage && (
            <p className="details-meta">
              Số lượt theo phase:{" "}
              {Object.entries(job.attempt_counts_by_stage)
                .map(
                  ([stage, counts]) =>
                    `${stage} ${Object.entries(counts)
                      .map(([phase, count]) => `${phase}:${count}`)
                      .join(",")}`,
                )
                .join(" · ")}
            </p>
          )}
          {Object.entries(stages).map(([stage, ledger]) => (
            <p className="details-meta" key={stage}>
              Chi phí {stage}: provider{" "}
              {ledger.provider_reported_cost_usd ?? "unknown"} · calculated{" "}
              {ledger.calculated_cost_usd ?? "unknown"} · estimated{" "}
              {ledger.estimated_cost_usd ?? "unknown"}
            </p>
          ))}
          <textarea
            aria-label="Bản nháp kể chuyện"
            className="touch-target"
            value={draft}
            readOnly
            onChange={() => undefined}
          />
        </details>
      )}
    </section>
  );
}
