PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS owners (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES owners(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_sessions_owner ON sessions(owner_id, expires_at);

CREATE TABLE IF NOT EXISTS login_failures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL COLLATE NOCASE,
    failed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_login_failures_email_time ON login_failures(email, failed_at);

CREATE TABLE IF NOT EXISTS campaigns (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES owners(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_campaigns_owner ON campaigns(owner_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS branches (
    id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    parent_branch_id TEXT REFERENCES branches(id),
    fork_checkpoint_id TEXT,
    head_turn_id TEXT,
    head_revision_id TEXT,
    state_version INTEGER NOT NULL DEFAULT 0 CHECK(state_version >= 0),
    head_checkpoint_id TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(campaign_id, name)
);
CREATE INDEX IF NOT EXISTS ix_branches_campaign ON branches(campaign_id);

CREATE TABLE IF NOT EXISTS profile_versions (
    id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    profile_key TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('world', 'character', 'persona', 'style')),
    version INTEGER NOT NULL CHECK(version > 0),
    data_json TEXT NOT NULL,
    supersedes_version_id TEXT REFERENCES profile_versions(id),
    created_at TEXT NOT NULL,
    UNIQUE(campaign_id, profile_key, version)
);
CREATE INDEX IF NOT EXISTS ix_profile_versions_campaign_key ON profile_versions(campaign_id, profile_key, version);

CREATE TABLE IF NOT EXISTS turns (
    id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    branch_id TEXT NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL CHECK(sequence > 0),
    action_text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(branch_id, sequence)
);
CREATE TABLE IF NOT EXISTS turn_revisions (
    id TEXT PRIMARY KEY,
    turn_id TEXT NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL CHECK(revision > 0),
    narrative_text TEXT NOT NULL,
    complete INTEGER NOT NULL CHECK(complete IN (0, 1)),
    selected INTEGER NOT NULL CHECK(selected IN (0, 1)),
    created_at TEXT NOT NULL,
    UNIQUE(turn_id, revision)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_turn_selected_revision ON turn_revisions(turn_id) WHERE selected = 1;
CREATE TABLE IF NOT EXISTS selected_revisions (
    branch_id TEXT NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    turn_id TEXT NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
    revision_id TEXT NOT NULL REFERENCES turn_revisions(id),
    PRIMARY KEY(branch_id, turn_id)
);

CREATE TABLE IF NOT EXISTS scene_versions (
    id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    branch_id TEXT NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    version INTEGER NOT NULL CHECK(version > 0),
    data_json TEXT NOT NULL,
    effective_state_version INTEGER NOT NULL CHECK(effective_state_version >= 0),
    effective_checkpoint_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(branch_id, version)
);

CREATE TABLE IF NOT EXISTS memory_items (
    id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    UNIQUE(id, campaign_id)
);

CREATE TABLE IF NOT EXISTS memory_versions (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    branch_id TEXT NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    version INTEGER NOT NULL CHECK(version > 0),
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    entity_ids_json TEXT NOT NULL,
    origin TEXT NOT NULL CHECK(origin IN ('user', 'import', 'ai')),
    status TEXT NOT NULL CHECK(status IN ('pending', 'approved', 'rejected', 'deleted')),
    pinned INTEGER NOT NULL CHECK(pinned IN (0, 1)),
    mandatory INTEGER NOT NULL CHECK(mandatory IN (0, 1)),
    knowledge_scope TEXT NOT NULL CHECK(knowledge_scope IN ('public', 'known_by', 'narrator_only')),
    known_by_json TEXT NOT NULL,
    source_revision_ids_json TEXT NOT NULL,
    effective_state_version INTEGER NOT NULL CHECK(effective_state_version > 0),
    effective_checkpoint_id TEXT NOT NULL,
    subject_id TEXT,
    predicate TEXT,
    value TEXT,
    object_id TEXT,
    supersedes_memory_id TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(memory_id, branch_id, version),
    FOREIGN KEY(memory_id, campaign_id) REFERENCES memory_items(id, campaign_id),
    FOREIGN KEY(supersedes_memory_id, campaign_id) REFERENCES memory_items(id, campaign_id)
);
CREATE INDEX IF NOT EXISTS ix_memory_campaign_branch ON memory_versions(campaign_id, branch_id, memory_id, version);

CREATE TABLE IF NOT EXISTS summary_versions (
    id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    branch_id TEXT NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    text TEXT NOT NULL,
    source_revision_ids_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending', 'approved', 'rejected')),
    created_at TEXT NOT NULL,
    UNIQUE(branch_id, version)
);

CREATE TABLE IF NOT EXISTS state_checkpoints (
    id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    branch_id TEXT NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    state_version INTEGER NOT NULL CHECK(state_version > 0),
    parent_checkpoint_id TEXT REFERENCES state_checkpoints(id),
    turn_id TEXT REFERENCES turns(id),
    revision_id TEXT REFERENCES turn_revisions(id),
    snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(branch_id, state_version)
);
CREATE INDEX IF NOT EXISTS ix_checkpoints_branch ON state_checkpoints(campaign_id, branch_id, state_version);
CREATE TABLE IF NOT EXISTS context_runs (
    id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    branch_id TEXT NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    checkpoint_id TEXT NOT NULL REFERENCES state_checkpoints(id),
    settings_revision INTEGER NOT NULL DEFAULT 0,
    source_ids_json TEXT NOT NULL,
    omission_reasons_json TEXT NOT NULL,
    token_budget_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS generation_jobs (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES owners(id) ON DELETE CASCADE,
    campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    branch_id TEXT NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    operation TEXT NOT NULL DEFAULT 'generation',
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL REFERENCES state_checkpoints(id),
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(owner_id, branch_id, operation, idempotency_key)
);
CREATE TABLE IF NOT EXISTS provider_attempts (
    id TEXT PRIMARY KEY,
    generation_job_id TEXT NOT NULL REFERENCES generation_jobs(id) ON DELETE CASCADE,
    stage TEXT NOT NULL CHECK(stage IN ('context', 'narration', 'consolidation')),
    stage_key TEXT NOT NULL UNIQUE,
    profile_snapshot_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    usage_json TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TRIGGER IF NOT EXISTS prevent_checkpoint_update
BEFORE UPDATE ON state_checkpoints BEGIN SELECT RAISE(ABORT, 'state checkpoints are immutable'); END;
CREATE TRIGGER IF NOT EXISTS prevent_checkpoint_delete
BEFORE DELETE ON state_checkpoints BEGIN SELECT RAISE(ABORT, 'state checkpoints are immutable'); END;
CREATE TRIGGER IF NOT EXISTS prevent_profile_version_update
BEFORE UPDATE ON profile_versions BEGIN SELECT RAISE(ABORT, 'profile versions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS prevent_profile_version_delete
BEFORE DELETE ON profile_versions BEGIN SELECT RAISE(ABORT, 'profile versions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS prevent_memory_version_update
BEFORE UPDATE ON memory_versions BEGIN SELECT RAISE(ABORT, 'memory versions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS prevent_memory_version_delete
BEFORE DELETE ON memory_versions BEGIN SELECT RAISE(ABORT, 'memory versions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS prevent_scene_version_update
BEFORE UPDATE ON scene_versions BEGIN SELECT RAISE(ABORT, 'scene versions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS prevent_scene_version_delete
BEFORE DELETE ON scene_versions BEGIN SELECT RAISE(ABORT, 'scene versions are immutable'); END;

INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (1, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
