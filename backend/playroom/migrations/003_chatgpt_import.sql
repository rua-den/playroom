-- Owner-selected ChatGPT source archive; no provider key or account-wide export.
CREATE TABLE IF NOT EXISTS chatgpt_import_sources (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES owners(id) ON DELETE CASCADE,
    campaign_id TEXT NOT NULL UNIQUE REFERENCES campaigns(id) ON DELETE CASCADE,
    branch_id TEXT NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    import_key TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    source_conversation_id TEXT NOT NULL,
    selected_source_json TEXT NOT NULL,
    paired_turns INTEGER NOT NULL CHECK(paired_turns > 0),
    warnings_json TEXT NOT NULL DEFAULT '[]',
    imported_at TEXT NOT NULL,
    UNIQUE(owner_id, import_key),
    UNIQUE(owner_id, payload_hash)
);
