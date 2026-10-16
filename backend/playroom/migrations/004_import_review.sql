CREATE TABLE IF NOT EXISTS import_review_checkpoints (
    campaign_id TEXT PRIMARY KEY REFERENCES campaigns(id) ON DELETE CASCADE,
    owner_id TEXT NOT NULL REFERENCES owners(id) ON DELETE CASCADE,
    source_checkpoint_id TEXT NOT NULL,
    approved_checkpoint_id TEXT,
    review_json TEXT NOT NULL DEFAULT '{}',
    approved_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_import_review_owner ON import_review_checkpoints(owner_id);
INSERT OR IGNORE INTO import_review_checkpoints(campaign_id, owner_id, source_checkpoint_id, review_json, created_at)
SELECT s.campaign_id, s.owner_id, b.head_checkpoint_id, '{}', s.imported_at
FROM chatgpt_import_sources s JOIN branches b ON b.id=s.branch_id;
