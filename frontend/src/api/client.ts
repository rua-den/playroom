import type { ApiErrorBody, CampaignProjection, GenerationJobSummary, LoginPayload, Owner } from "./types";

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

async function request<T>(path: string, init: RequestInit = {}, notifyAuthExpired = true): Promise<T> {
  const requestGeneration = authGeneration;
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("content-type")) headers.set("content-type", "application/json");
  const response = await fetch(path, { ...init, headers, credentials: "same-origin" });
  if (response.ok) {
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }
  let body: ApiErrorBody = {};
  try {
    const text = await response.text();
    body = text ? (JSON.parse(text) as ApiErrorBody) : {};
  } catch { /* plain HTTP error */ }
  if (response.status === 401 && notifyAuthExpired && requestGeneration === authGeneration) {
    authGeneration += 1;
    privateCache.clear();
    authExpiredListeners.forEach((listener) => listener());
  }
  const detail = Array.isArray(body.detail) ? body.detail.map((item) => item.msg).filter(Boolean).join(", ") : body.detail;
  throw new ApiError(response.status, detail || `Yêu cầu thất bại (${response.status})`, body.code);
}

export const api = {
  me: (options: { notifyAuthExpired?: boolean } = {}) => request<Owner>("/api/auth/me", {}, options.notifyAuthExpired ?? true),
  getCampaignProjection: (campaignId: string, branchId: string) => request<CampaignProjection>(`/api/campaigns/${encodeURIComponent(campaignId)}/projection?branch_id=${encodeURIComponent(branchId)}`),
  getGenerationJobs: (campaignId: string, branchId: string, limit = 20) => request<{ jobs: GenerationJobSummary[] }>(`/api/campaigns/${encodeURIComponent(campaignId)}/generation-jobs?branch_id=${encodeURIComponent(branchId)}&limit=${limit}`),
  login: async (payload: LoginPayload) => {
    activeLogout?.abort();
    activeLogout = null;
    const result = await request<{ owner: Owner }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify(payload),
    }, false);
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
      await request<void>("/api/auth/logout", { method: "POST", signal: controller.signal }, false);
      return { ok: true, generation };
    } catch {
      return { ok: false, generation };
    } finally {
      if (activeLogout === controller) activeLogout = null;
      if (authGeneration === generation) privateCache.clear();
    }
  },
};
