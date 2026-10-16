export interface Owner {
  id: string;
  email: string;
}

export interface DemoInfo { mode: "synthetic" | "production"; label: string; provider?: string; }

export interface LoginPayload {
  email: string;
  password: string;
}

export interface ApiErrorBody {
  detail?: string | Array<{ msg?: string }>;
  code?: string;
}

export interface CampaignProjectionProfile {
  profile_key: string;
  kind: "world" | "persona" | "style" | "character";
  version: number;
  data: Record<string, unknown>;
}

export interface CampaignSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}

export interface CampaignDetail extends CampaignSummary {
  branch_id: string;
  state_version: number;
  checkpoint_id: string;
  profiles: Record<string, { kind: string; data: Record<string, unknown> }>;
}

export interface CampaignCreatePayload {
  title: string;
  world: Record<string, unknown>;
  characters: Array<{ id: string; name: string; aliases: string[]; [key: string]: unknown }>;
  persona: Record<string, unknown>;
}

export interface CampaignTranscriptEntry {
  revision_id: string;
  turn_id: string;
  sequence: number;
  action_text: string;
  revision: number;
  narrative_text: string;
  complete: boolean;
  selected: boolean;
  input_segments?: Array<{ kind: "dialogue" | "action"; text: string }> | null;
  output_segments?: Array<{ kind: "narration" | "dialogue"; text: string; character_id?: string; profile_version_id?: string }> | null;
}

export interface GenerationJobSummary {
  id: string;
  campaign_id: string;
  branch_id: string;
  checkpoint_id: string;
  status: "queued" | "running" | "cancelling" | "interrupted" | "candidate" | "committed" | "failed" | "cancelled";
  mode: string | null;
  action: string | null;
  created_at: string;
  cancel_requested: boolean;
}

export interface CampaignProjection {
  campaign: { id: string; title: string; created_at: string; updated_at: string; archived_at: string | null };
  branch: { id: string; name: string; state_version: number; checkpoint_id: string };
  checkpoint: { id: string; state_version: number; parent_checkpoint_id: string | null; selected_revision_ids: string[]; retrieval_policy: "auto" | "important_only" | "disabled" };
  profiles: Record<string, CampaignProjectionProfile>;
  scene: { id: string; version: number; data: Record<string, unknown> } | null;
  transcript: CampaignTranscriptEntry[];
    jobs: GenerationJobSummary[];
    import_review?: { required: boolean; approved: boolean; approved_checkpoint_id?: string | null; review: Record<string, boolean> };
}

export interface ProfileUpdateResult { state_version: number; checkpoint_id: string; previous_state_version?: number; }
export interface MemoryVersion {
  memory_id: string; id: string; version: number; kind: string; text: string; origin: "user" | "ai" | "import";
  status: "pending" | "approved" | "rejected" | "deleted"; pinned: boolean; mandatory?: boolean;
  source_revision_ids: string[]; entity_ids?: string[]; knowledge_scope: "public" | "known_by" | "narrator_only"; known_by: string[];
  subject_id?: string | null; predicate?: string | null; value?: string | null; object_id?: string | null; supersedes_memory_id?: string | null;
  effective_state_version?: number; effective_checkpoint_id?: string;
}
export interface MemoryCreatePayload {
  branch_id: string; expected_state_version: number; kind: string; text: string; source_revision_ids: string[];
  entity_ids: string[]; knowledge_scope: "public" | "known_by" | "narrator_only"; known_by: string[];
  subject_id?: string | null; predicate?: string | null; value?: string | null; object_id?: string | null; supersedes_id?: string | null;
}
export interface MemoryUpdatePayload {
  branch_id: string; expected_state_version: number; text?: string; pinned?: boolean; entity_ids?: string[];
  knowledge_scope?: "public" | "known_by" | "narrator_only"; known_by?: string[];
  subject_id?: string | null; predicate?: string | null; value?: string | null; object_id?: string | null; supersedes_id?: string | null;
}
export interface SceneRecord { id: string; name?: string; present_ids: string[]; [key: string]: unknown; }
export interface SceneState { focus_scene_id: string | null; scenes: SceneRecord[]; }
export interface SceneResponse { focus_scene_id: string | null; scenes: Record<string, SceneRecord>; effective_cursor?: { state_version: number; checkpoint_id: string }; read_cursor?: { state_version: number; checkpoint_id: string }; }

export interface CredentialSummary { id: string; version: number; revoked: boolean; masked: string; secret: null; }
export interface ModelProfileSummary { id: string; version: number; model: string; model_label?: string; provider: string; endpoint?: string; output_limit?: number; context_limit?: number; credential_tier?: "free" | "paid" | "unknown"; pricing_verified?: boolean; pricing?: { prompt?: string; completion?: string; currency?: string; unit?: string }; credential_metadata?: { free_model_daily_requests?: number | null; quota_period?: string | null; quota_source?: string | null }; structured_output?: boolean; native_structured_output?: boolean; structured_schema_parameter?: string | null; profile_hash?: string; }
export interface ProviderRoleBinding { id: string; version: number; profile_hash?: string; }
export interface ProviderSettings { settings_revision: number; settings_hash?: string; mode: "economy" | "quality"; policy: "free_only" | "capped_paid"; confirmed_usd_cap: string | null; roles: { context?: ProviderRoleBinding; narrator?: ProviderRoleBinding; consolidation?: ProviderRoleBinding }; budgets: Record<string, { input_limit: number; requested_output: number; wrapper_buffer: number }>; budgets_configured?: boolean; }
export interface SettingsUpdatePayload { context_profile_id?: string; narrator_profile_id?: string; consolidation_profile_id?: string; mode?: "economy" | "quality"; policy?: "free_only" | "capped_paid"; confirmed_usd_cap?: string | null; budgets?: Record<string, { input_limit: number; requested_output: number; wrapper_buffer: number }>; }

export interface ContextPreview { id: string; campaign_id: string; branch_id: string; checkpoint_id: string; action: string; status: "ready" | "blocked" | "stale"; profile_id: string; payload?: Record<string, unknown>; estimated_tokens?: number; omitted?: string[]; }
export interface GenerationEvent { id: number; stage: string | null; event_type: string; offset: number; content: string; payload?: Record<string, unknown>; created_at?: string; }
export interface GenerationLedgerStage {
  provider_reported_cost_usd?: string | null; provider_reported_status?: "provider_reported" | "unknown";
  calculated_cost_usd?: string | null; calculated_status?: "calculated" | "unknown";
  estimated_cost_usd?: string | null; estimated_status?: "estimated" | "unknown";
  actual_cost_usd?: string | null; actual_status?: "provider_reported" | "calculated" | "estimated" | "unknown";
  cost_provenance?: string; usage?: Record<string, unknown> | null;
}
export interface GenerationCostLedger { policy?: string; cap?: string | null; stages?: Record<string, GenerationLedgerStage>; actual_status?: string; actual_total_usd?: string | null; provider_reported_total_usd?: string | null; calculated_total_usd?: string | null; }
export interface GenerationJob { id: string; campaign_id: string; branch_id: string; checkpoint_id: string; status: GenerationJobSummary["status"]; action?: string | null; draft: string; offset: number; offset_unit: "utf16_code_units"; failure?: { code?: string; message?: string } | null; candidate?: boolean; usage?: Record<string, unknown>; events?: GenerationEvent[]; attempt_counts_by_stage?: Record<string, Record<string, number>>; cost_ledger?: GenerationCostLedger; }

export interface PaidTrialSummary {
  id?: string; state: "none" | "active" | "expired" | "revoked" | "overrun";
  profile_id?: string; profile_version?: number; total_cap_usd?: string;
  per_send_cap_usd?: string; max_jobs?: number; expires_at?: string;
  reserved_usd: string; remaining_usd: string; jobs_used: number;
}
