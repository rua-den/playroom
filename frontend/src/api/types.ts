export interface Owner {
  id: string;
  email: string;
}

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
