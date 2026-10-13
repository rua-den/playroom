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
  checkpoint: { id: string; state_version: number; parent_checkpoint_id: string | null; selected_revision_ids: string[] };
  profiles: Record<string, CampaignProjectionProfile>;
  scene: { id: string; version: number; data: Record<string, unknown> } | null;
  transcript: CampaignTranscriptEntry[];
  jobs: GenerationJobSummary[];
}
