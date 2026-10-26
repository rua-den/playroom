import type {
  ApiErrorBody,
  BranchSummary,
  CampaignCreatePayload,
  CampaignDetail,
  CampaignProjection,
  CampaignSummary,
  GenerationJobSummary,
  LoginPayload,
  Owner,
  MemoryVersion,
  MemoryCreatePayload,
  MemoryUpdatePayload,
  ProfileUpdateResult,
  SceneResponse,
  CredentialSummary,
  ModelProfileSummary,
  ProviderSettings,
  SettingsUpdatePayload,
} from "./types";

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;

  constructor(status: number, message: string, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

/** Private data is memory-only by design; logout clears every entry. */
export const privateCache = new Map<string, unknown>();
const authExpiredListeners = new Set<() => void>();
let authGeneration = 0;
let activeLogout: AbortController | null = null;

export function getAuthGeneration(): number {
  return authGeneration;
}

export function subscribeAuthExpired(listener: () => void): () => void {
  authExpiredListeners.add(listener);
  return () => authExpiredListeners.delete(listener);
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  notifyAuthExpired = true,
): Promise<T> {
  const requestGeneration = authGeneration;
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("content-type"))
    headers.set("content-type", "application/json");
  const response = await fetch(path, {
    ...init,
    headers,
    credentials: "same-origin",
  });
  if (response.ok) {
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }
  let body: ApiErrorBody = {};
  try {
    const text = await response.text();
    body = text ? (JSON.parse(text) as ApiErrorBody) : {};
  } catch {
    /* plain HTTP error */
  }
  if (
    response.status === 401 &&
    notifyAuthExpired &&
    requestGeneration === authGeneration
  ) {
    authGeneration += 1;
    privateCache.clear();
    authExpiredListeners.forEach((listener) => listener());
  }
  const detail = Array.isArray(body.detail)
    ? body.detail
        .map((item) => item.msg)
        .filter(Boolean)
        .join(", ")
    : body.detail;
  throw new ApiError(
    response.status,
    detail || `Yêu cầu thất bại (${response.status})`,
    body.code,
  );
}

export const api = {
  getDemoInfo: () =>
    request<import("./types").DemoInfo>("/api/demo/info", {}, false),
  me: (options: { notifyAuthExpired?: boolean } = {}) =>
    request<Owner>("/api/auth/me", {}, options.notifyAuthExpired ?? true),
  listCampaigns: (trashed = false) => request<CampaignSummary[]>(`/api/campaigns${trashed ? "?trashed=true" : ""}`),
  deleteCampaign: (campaignId: string) =>
    request<CampaignSummary>(`/api/campaigns/${encodeURIComponent(campaignId)}`, { method: "DELETE" }),
  restoreCampaign: (campaignId: string) =>
    request<CampaignSummary>(`/api/campaigns/${encodeURIComponent(campaignId)}/restore`, { method: "POST" }),
  getCampaign: (campaignId: string) =>
    request<CampaignDetail>(`/api/campaigns/${encodeURIComponent(campaignId)}`),
  createCampaign: (payload: CampaignCreatePayload) =>
    request<{
      id: string;
      title: string;
      branch_id: string;
      character_ids: string[];
    }>("/api/campaigns", { method: "POST", body: JSON.stringify(payload) }),
  previewChatGptImport: (conversation: Record<string, unknown>) =>
    request<{
      conversation_id: string;
      title: string;
      turn_count: number;
      skipped_messages: number;
      warnings: string[];
      sample_first: { action_text: string; narrative_text: string };
      sample_last: { action_text: string; narrative_text: string };
    }>("/api/transfers/chatgpt/preview", {
      method: "POST",
      body: JSON.stringify({ conversation }),
    }),
  importChatGpt: (
    conversation: Record<string, unknown>,
    config: {
      title: string;
      world: { name: string };
      persona: { name: string };
      characters: Array<{ id: string; name: string; aliases: string[] }>;
    },
    importKey: string,
  ) =>
    request<{
      campaign_id: string;
      branch_id: string;
      checkpoint_id: string;
      turn_count: number;
      imported_turns: number;
      complete: boolean;
      already_imported: boolean;
      resumed: boolean;
    }>("/api/transfers/chatgpt/import", {
      method: "POST",
      body: JSON.stringify({ conversation, config, import_key: importKey }),
    }),
  previewLegacyImport: (bundle: Record<string, unknown>) =>
    request<{
      format: string;
      schema_version: string;
      title: string;
      turn_count: number;
      missing_history: boolean;
      counts: {
        characters: number;
        canon_facts: number;
        relationships: number;
        timeline_events: number;
        player_excerpts: number;
      };
      checkpoint: {
        last_completed_chapter: number;
        next_chapter: number;
        next_chapter_written: boolean;
        present_character_count: number;
      };
      warnings: string[];
      requires_owner_review: boolean;
    }>("/api/transfers/legacy/preview", {
      method: "POST",
      body: JSON.stringify({ bundle }),
    }),
  importLegacyBundle: (bundle: Record<string, unknown>, importKey: string) =>
    request<{
      campaign_id: string;
      branch_id: string;
      checkpoint_id: string;
      turn_count: number;
      already_imported: boolean;
    }>("/api/transfers/legacy/import", {
      method: "POST",
      body: JSON.stringify({ bundle, import_key: importKey }),
    }),
  approveChatGptImport: (
    campaignId: string,
    payload: {
      branch_id: string;
      checkpoint_id: string;
      review: {
        persona: boolean;
        npc_voice_presence: boolean;
        canon_known_by_narrator_only: boolean;
        missing_history: boolean;
        provider_data?: boolean;
      };
    },
  ) =>
    request<{ required: boolean; approved: boolean }>(
      `/api/transfers/chatgpt/${encodeURIComponent(campaignId)}/review`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  getCampaignProjection: (campaignId: string, branchId: string) =>
    request<CampaignProjection>(
      `/api/campaigns/${encodeURIComponent(campaignId)}/projection?branch_id=${encodeURIComponent(branchId)}`,
    ),
  listBranches: (campaignId: string) =>
    request<{ branches: BranchSummary[] }>(
      `/api/campaigns/${encodeURIComponent(campaignId)}/branches`,
    ),
  forkBranch: (
    campaignId: string,
    payload: import("./types").ForkBranchPayload,
  ) =>
    request<BranchSummary>(
      `/api/campaigns/${encodeURIComponent(campaignId)}/branches`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  getGenerationJobs: (campaignId: string, branchId: string, limit = 20) =>
    request<{ jobs: GenerationJobSummary[] }>(
      `/api/campaigns/${encodeURIComponent(campaignId)}/generation-jobs?branch_id=${encodeURIComponent(branchId)}&limit=${limit}`,
    ),
  updateProfile: (
    campaignId: string,
    profileKey: string,
    payload: {
      branch_id: string;
      expected_state_version: number;
      data: Record<string, unknown>;
    },
  ) =>
    request<ProfileUpdateResult>(
      `/api/campaigns/${encodeURIComponent(campaignId)}/profiles/${encodeURIComponent(profileKey)}`,
      { method: "PATCH", body: JSON.stringify(payload) },
    ),
  addCharacter: (
    campaignId: string,
    payload: {
      branch_id: string;
      expected_state_version: number;
      character: Record<string, unknown>;
    },
  ) =>
    request<ProfileUpdateResult & { character_id: string }>(
      `/api/campaigns/${encodeURIComponent(campaignId)}/characters`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  removeProfile: (
    campaignId: string,
    profileKey: string,
    branchId: string,
    stateVersion: number,
  ) =>
    request<ProfileUpdateResult>(
      `/api/campaigns/${encodeURIComponent(campaignId)}/profiles/${encodeURIComponent(profileKey)}?branch_id=${encodeURIComponent(branchId)}&expected_state_version=${stateVersion}`,
      { method: "DELETE" },
    ),
  listMemory: (campaignId: string, branchId: string) =>
    request<MemoryVersion[]>(
      `/api/campaigns/${encodeURIComponent(campaignId)}/memory?branch_id=${encodeURIComponent(branchId)}`,
    ),
  listProposals: (campaignId: string, branchId: string) =>
    request<MemoryVersion[]>(
      `/api/campaigns/${encodeURIComponent(campaignId)}/memory/proposals?branch_id=${encodeURIComponent(branchId)}`,
    ),
  listMemoryHistory: (campaignId: string, memoryId: string, branchId: string) =>
    request<MemoryVersion[]>(
      `/api/campaigns/${encodeURIComponent(campaignId)}/memory/${encodeURIComponent(memoryId)}/history?branch_id=${encodeURIComponent(branchId)}`,
    ),
  createMemory: (campaignId: string, payload: MemoryCreatePayload) =>
    request<MemoryVersion>(
      `/api/campaigns/${encodeURIComponent(campaignId)}/memory`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  updateMemory: (
    campaignId: string,
    memoryId: string,
    payload: MemoryUpdatePayload,
  ) =>
    request<MemoryVersion>(
      `/api/campaigns/${encodeURIComponent(campaignId)}/memory/${encodeURIComponent(memoryId)}`,
      { method: "PATCH", body: JSON.stringify(payload) },
    ),
  reviewMemory: (
    campaignId: string,
    memoryId: string,
    action: "approve" | "reject",
    branchId: string,
    stateVersion: number,
  ) =>
    request<MemoryVersion>(
      `/api/campaigns/${encodeURIComponent(campaignId)}/memory/${encodeURIComponent(memoryId)}/${action}?branch_id=${encodeURIComponent(branchId)}&expected_state_version=${stateVersion}`,
      { method: "POST" },
    ),
  deleteMemory: (
    campaignId: string,
    memoryId: string,
    branchId: string,
    stateVersion: number,
  ) =>
    request<MemoryVersion>(
      `/api/campaigns/${encodeURIComponent(campaignId)}/memory/${encodeURIComponent(memoryId)}?branch_id=${encodeURIComponent(branchId)}&expected_state_version=${stateVersion}`,
      { method: "DELETE" },
    ),
  getScene: (campaignId: string, branchId: string) =>
    request<SceneResponse>(
      `/api/campaigns/${encodeURIComponent(campaignId)}/scene?branch_id=${encodeURIComponent(branchId)}`,
    ),
  updateScene: (
    campaignId: string,
    payload: {
      branch_id: string;
      expected_state_version: number;
      scene_state: import("./types").SceneState;
    },
  ) =>
    request<ProfileUpdateResult>(
      `/api/campaigns/${encodeURIComponent(campaignId)}/scene`,
      { method: "PUT", body: JSON.stringify(payload) },
    ),
  updateRetrievalPolicy: (
    campaignId: string,
    payload: {
      branch_id: string;
      expected_state_version: number;
      policy: "auto" | "important_only" | "disabled";
    },
  ) =>
    request<ProfileUpdateResult & { policy: string }>(
      `/api/campaigns/${encodeURIComponent(campaignId)}/retrieval-policy`,
      { method: "PUT", body: JSON.stringify(payload) },
    ),
  listCredentials: () =>
    request<CredentialSummary[]>("/api/provider/credentials"),
  addCredential: (secret: string) =>
    request<CredentialSummary>("/api/provider/credentials", {
      method: "POST",
      body: JSON.stringify({ secret }),
    }),
  listProviderProfiles: () =>
    request<ModelProfileSummary[]>("/api/provider/profiles"),
  getPaidTrial: () =>
    request<import("./types").PaidTrialSummary>("/api/provider/trials/current"),
  createPaidTrial: (payload: {
    profile_id: string;
    profile_version: number;
    total_cap_usd: string;
    per_send_cap_usd: string;
    max_jobs: number;
    expires_at: string;
  }) =>
    request<import("./types").PaidTrialSummary>("/api/provider/trials", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  revokePaidTrial: (id: string) =>
    request<import("./types").PaidTrialSummary>(
      `/api/provider/trials/${encodeURIComponent(id)}/revoke`,
      { method: "POST" },
    ),
  getProviderSettings: () =>
    request<ProviderSettings>("/api/provider/settings"),
  updateProviderSettings: (payload: SettingsUpdatePayload) =>
    request<ProviderSettings>("/api/provider/settings", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  verifyProviderProfile: (payload: {
    provider?: "openrouter" | "ollama";
    credential_id: string;
    model: string;
    endpoint: string;
    provider_tag?: string;
  }) =>
    request<ModelProfileSummary>("/api/provider/profiles/verify", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  createCustomProfile: (payload: {
    endpoint: string;
    model: string;
    credential_id?: string;
  }) =>
    request<ModelProfileSummary>("/api/provider/profiles/custom", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  createContextPreview: (
    campaignId: string,
    payload: { branch_id: string; action: string; profile_id: string },
  ) =>
    request<import("./types").ContextPreview>(
      `/api/campaigns/${encodeURIComponent(campaignId)}/context/previews`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  getContextPreview: (previewId: string) =>
    request<import("./types").ContextPreview>(
      `/api/context/previews/${encodeURIComponent(previewId)}`,
    ),
  generate: (
    campaignId: string,
    payload: {
      branch_id: string;
      action: string;
      idempotency_key: string;
      checkpoint_id: string;
      preview_id?: string;
      mode?: string;
      policy?: string;
      cap?: string | null;
    },
  ) =>
    request<import("./types").GenerationJob>(
      `/api/campaigns/${encodeURIComponent(campaignId)}/generate`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  getGenerationJob: (jobId: string) =>
    request<import("./types").GenerationJob>(
      `/api/generation/jobs/${encodeURIComponent(jobId)}`,
    ),
  getGenerationByKey: (branchId: string, idempotencyKey: string) =>
    request<import("./types").GenerationJob>(
      `/api/generation/jobs/by-key?branch_id=${encodeURIComponent(branchId)}&idempotency_key=${encodeURIComponent(idempotencyKey)}`,
    ),
  getGenerationEvents: (jobId: string, after = 0) =>
    request<{ events: import("./types").GenerationEvent[] }>(
      `/api/generation/jobs/${encodeURIComponent(jobId)}/events?after=${after}`,
    ),
  getGenerationContent: (jobId: string) =>
    request<import("./types").GenerationJob>(
      `/api/generation/jobs/${encodeURIComponent(jobId)}/content`,
    ),
  cancelGeneration: (jobId: string) =>
    request<import("./types").GenerationJob>(
      `/api/generation/jobs/${encodeURIComponent(jobId)}/cancel`,
      { method: "POST" },
    ),
  editGenerationDraft: (jobId: string, draft: string) =>
    request<import("./types").GenerationJob>(
      `/api/generation/jobs/${encodeURIComponent(jobId)}/draft`,
      { method: "PUT", body: JSON.stringify({ draft }) },
    ),
  commitGeneration: (jobId: string) =>
    request<import("./types").ProfileUpdateResult>(
      `/api/generation/jobs/${encodeURIComponent(jobId)}/commit`,
      { method: "POST" },
    ),
  login: async (payload: LoginPayload) => {
    activeLogout?.abort();
    activeLogout = null;
    const result = await request<{ owner: Owner }>(
      "/api/auth/login",
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
      false,
    );
    authGeneration += 1;
    return result;
  },
  logout: async (): Promise<{ ok: boolean; generation: number }> => {
    activeLogout?.abort();
    const controller = new AbortController();
    activeLogout = controller;
    const generation = ++authGeneration;
    privateCache.clear();
    try {
      await request<void>(
        "/api/auth/logout",
        { method: "POST", signal: controller.signal },
        false,
      );
      return { ok: true, generation };
    } catch {
      return { ok: false, generation };
    } finally {
      if (activeLogout === controller) activeLogout = null;
      if (authGeneration === generation) privateCache.clear();
    }
  },
};
