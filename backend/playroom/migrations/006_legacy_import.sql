-- Separate private, selected structured legacy source; never synthesize historical turns.
CREATE TABLE IF NOT EXISTS legacy_import_sources (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES owners(id) ON DELETE CASCADE,
    campaign_id TEXT NOT NULL UNIQUE REFERENCES campaigns(id) ON DELETE CASCADE,
    branch_id TEXT NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    import_key TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    selected_source_json TEXT NOT NULL,
    warnings_json TEXT NOT NULL,
    canon_count INTEGER NOT NULL,
    event_count INTEGER NOT NULL,
    excerpt_count INTEGER NOT NULL,
    imported_at TEXT NOT NULL,
    UNIQUE(owner_id, import_key),
    UNIQUE(owner_id, payload_hash)
);
