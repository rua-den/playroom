from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import unquote, urlsplit

from fastapi import Request
from .domain import StateConflict


def _database_path(path_or_url: str | Path) -> str:
    value = str(path_or_url)
    if value.startswith("sqlite://"):
        parsed = urlsplit(value)
        if parsed.scheme != "sqlite" or parsed.netloc not in {"", "localhost"}:
            raise ValueError("SQLite database URL must be local")
        value = unquote(parsed.path)
        if value == "/:memory:":
            return ":memory:"
        if len(value) >= 3 and value[0] == "/" and value[2] == ":":
            value = value[1:]
    if value in {":memory:", "file::memory:?cache=shared"} or value.startswith("file:"):
        return value
    path = Path(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def connect(path_or_url: str | Path) -> sqlite3.Connection:
    path = _database_path(path_or_url)
    connection = sqlite3.connect(path, timeout=10, isolation_level=None, check_same_thread=False, uri=path.startswith("file:"))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    if path != ":memory:" and not path.startswith("file:"):
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
    return connection


def _add_column_if_missing(connection: sqlite3.Connection, table: str, name: str, definition: str) -> None:
    try:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
    except sqlite3.OperationalError as exc:
        # Another startup connection may have observed the same missing column
        # and added it first. Keep the migration idempotent while preserving
        # unrelated SQLite errors for the caller to handle.
        if "duplicate column name" not in str(exc).casefold():
            raise
        if name not in {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}:
            raise


def migrate(connection: sqlite3.Connection) -> None:
    migration = Path(__file__).parent / "migrations" / "001_initial.sql"
    connection.executescript(migration.read_text(encoding="utf-8"))
    # Additive paid-trial grant ledger: idempotent, owner-scoped and durable.
    paid_trials = Path(__file__).parent / "migrations" / "002_paid_trials.sql"
    connection.executescript(paid_trials.read_text(encoding="utf-8"))
    source_imports = Path(__file__).parent / "migrations" / "003_chatgpt_import.sql"
    connection.executescript(source_imports.read_text(encoding="utf-8"))
    import_review = Path(__file__).parent / "migrations" / "004_import_review.sql"
    connection.executescript(import_review.read_text(encoding="utf-8"))
    legacy_import = Path(__file__).parent / "migrations" / "006_legacy_import.sql"
    connection.executescript(legacy_import.read_text(encoding="utf-8"))
    with transaction(connection):
        if connection.execute("SELECT 1 FROM schema_migrations WHERE version=7").fetchone() is None:
            owner_columns = {row[1] for row in connection.execute("PRAGMA table_info(owners)")}
            if "username" not in owner_columns:
                _add_column_if_missing(connection, "owners", "username", "TEXT NOT NULL DEFAULT ''")
            if "is_admin" not in owner_columns:
                _add_column_if_missing(connection, "owners", "is_admin", "INTEGER NOT NULL DEFAULT 0 CHECK(is_admin IN (0,1))")
            connection.execute("UPDATE owners SET username=email WHERE username=''")
            connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_owners_username ON owners(username COLLATE NOCASE)")
            connection.execute("CREATE TABLE IF NOT EXISTS account_deletion_requests (owner_id TEXT NOT NULL, campaign_id TEXT)")
            connection.execute(
                "UPDATE owners SET is_admin=1 WHERE id=(SELECT id FROM owners ORDER BY created_at,id LIMIT 1) "
                "AND NOT EXISTS(SELECT 1 FROM owners WHERE is_admin=1)"
            )
            connection.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (7, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))")
    source_columns = {row[1] for row in connection.execute("PRAGMA table_info(chatgpt_import_sources)")}
    if "skipped_messages" not in source_columns:
        _add_column_if_missing(connection, "chatgpt_import_sources", "skipped_messages", "INTEGER")
    # ChatGPT source imports are resumed in bounded committed chunks. Keep these
    # additive columns individually guarded so an interrupted schema upgrade is
    # safe to rerun on the next launch.
    source_columns = {row[1] for row in connection.execute("PRAGMA table_info(chatgpt_import_sources)")}
    for name, definition in (
        ("import_status", "TEXT NOT NULL DEFAULT 'complete'"),
        ("imported_turns", "INTEGER NOT NULL DEFAULT 0"),
        ("import_updated_at", "TEXT"),
    ):
        if name not in source_columns:
            _add_column_if_missing(connection, "chatgpt_import_sources", name, definition)
    connection.execute(
        "UPDATE chatgpt_import_sources "
        "SET imported_turns=paired_turns, import_status='complete', "
        "import_updated_at=COALESCE(import_updated_at, imported_at) "
        "WHERE import_status='complete' AND imported_turns=0"
    )
    # Migration 004 historically backfills a review row for every ChatGPT
    # source. Resumable imports intentionally persist their source before the
    # final chunk, so remove only unapproved synthetic backfills for unfinished
    # sources. The final chunk recreates the row at the actual final checkpoint.
    connection.execute(
        "DELETE FROM import_review_checkpoints "
        "WHERE approved_checkpoint_id IS NULL AND campaign_id IN ("
        "SELECT campaign_id FROM chatgpt_import_sources WHERE import_status='importing'"
        ")"
    )
    columns = {row[1] for row in connection.execute("PRAGMA table_info(campaigns)")}
    if "archived_at" not in columns:
        _add_column_if_missing(connection, "campaigns", "archived_at", "TEXT")
    columns = {row[1] for row in connection.execute("PRAGMA table_info(campaigns)")}
    if "deleted_at" not in columns:
        _add_column_if_missing(connection, "campaigns", "deleted_at", "TEXT")
    generation_columns = {row[1] for row in connection.execute("PRAGMA table_info(generation_jobs)")}
    if generation_columns:
        for name, definition in (("action", "TEXT NOT NULL DEFAULT ''"), ("mode", "TEXT NOT NULL DEFAULT 'economy'"), ("policy", "TEXT NOT NULL DEFAULT 'free_only'"), ("draft", "TEXT NOT NULL DEFAULT ''"), ("output_segments_json", "TEXT"), ("failure_json", "TEXT"), ("usage_json", "TEXT"), ("settings_revision", "INTEGER NOT NULL DEFAULT 0"), ("settings_snapshot_json", "TEXT NOT NULL DEFAULT '{}'"), ("profile_snapshot_json", "TEXT NOT NULL DEFAULT '{}'"), ("credential_version", "TEXT"), ("reserved_cost_json", "TEXT"), ("execution_epoch", "TEXT"), ("cancel_requested", "INTEGER NOT NULL DEFAULT 0"), ("final_context_json", "TEXT"), ("preview_id", "TEXT"), ("preview_snapshot_json", "TEXT")):
            if name not in generation_columns:
                _add_column_if_missing(connection, "generation_jobs", name, definition)
    attempt_columns = {row[1] for row in connection.execute("PRAGMA table_info(provider_attempts)")}
    if attempt_columns:
        for name, definition in (("output_text", "TEXT NOT NULL DEFAULT ''"), ("output_offset", "INTEGER NOT NULL DEFAULT 0"), ("failure_json", "TEXT"), ("request_json", "TEXT NOT NULL DEFAULT '{}'"), ("dispatched_at", "TEXT"), ("claim_epoch", "TEXT"), ("cancel_requested", "INTEGER NOT NULL DEFAULT 0")):
            if name not in attempt_columns:
                _add_column_if_missing(connection, "provider_attempts", name, definition)
    context_run_columns = {row[1] for row in connection.execute("PRAGMA table_info(context_runs)")}
    if context_run_columns:
        for name, definition in (("generation_job_id", "TEXT"), ("request_json", "TEXT NOT NULL DEFAULT '{}'"), ("wire_json", "TEXT NOT NULL DEFAULT '{}'"), ("counter_id", "TEXT NOT NULL DEFAULT 'utf8-bytes-div-3'"), ("counter_mode", "TEXT NOT NULL DEFAULT 'estimated'")):
            if name not in context_run_columns:
                _add_column_if_missing(connection, "context_runs", name, definition)
    turns_columns = {row[1] for row in connection.execute("PRAGMA table_info(turns)")}
    if turns_columns and "input_segments_json" not in turns_columns:
        _add_column_if_missing(connection, "turns", "input_segments_json", "TEXT")
    revisions_columns = {row[1] for row in connection.execute("PRAGMA table_info(turn_revisions)")}
    if revisions_columns and "output_segments_json" not in revisions_columns:
        _add_column_if_missing(connection, "turn_revisions", "output_segments_json", "TEXT")
    connection.execute("CREATE TABLE IF NOT EXISTS model_profile_versions (id TEXT NOT NULL, owner_id TEXT NOT NULL REFERENCES owners(id) ON DELETE CASCADE, version INTEGER NOT NULL, snapshot_json TEXT NOT NULL, profile_hash TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(owner_id, id, version))")
    connection.execute("CREATE TRIGGER IF NOT EXISTS prevent_model_profile_update BEFORE UPDATE ON model_profile_versions BEGIN SELECT RAISE(ABORT, 'model profiles are immutable'); END")
    connection.execute("CREATE TRIGGER IF NOT EXISTS prevent_model_profile_delete BEFORE DELETE ON model_profile_versions BEGIN SELECT RAISE(ABORT, 'model profiles are immutable'); END")
    connection.execute("CREATE TABLE IF NOT EXISTS owner_settings_versions (owner_id TEXT NOT NULL REFERENCES owners(id) ON DELETE CASCADE, revision INTEGER NOT NULL, settings_json TEXT NOT NULL, settings_hash TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(owner_id, revision))")
    connection.execute("CREATE TRIGGER IF NOT EXISTS prevent_owner_settings_update BEFORE UPDATE ON owner_settings_versions BEGIN SELECT RAISE(ABORT, 'owner settings are immutable'); END")
    connection.execute("CREATE TRIGGER IF NOT EXISTS prevent_owner_settings_delete BEFORE DELETE ON owner_settings_versions BEGIN SELECT RAISE(ABORT, 'owner settings are immutable'); END")
    with transaction(connection):
        if connection.execute("SELECT 1 FROM schema_migrations WHERE version=8").fetchone() is None:
            for trigger, table, condition in (
                ("prevent_checkpoint_delete", "state_checkpoints", "campaign_id=OLD.campaign_id"),
                ("prevent_profile_version_delete", "profile_versions", "campaign_id=OLD.campaign_id"),
                ("prevent_memory_version_delete", "memory_versions", "campaign_id=OLD.campaign_id"),
                ("prevent_scene_version_delete", "scene_versions", "campaign_id=OLD.campaign_id"),
                ("prevent_context_preview_delete", "context_previews", "owner_id=OLD.owner_id AND campaign_id IS NULL"),
                ("prevent_model_profile_delete", "model_profile_versions", "owner_id=OLD.owner_id AND campaign_id IS NULL"),
                ("prevent_owner_settings_delete", "owner_settings_versions", "owner_id=OLD.owner_id AND campaign_id IS NULL"),
            ):
                connection.execute(f"DROP TRIGGER IF EXISTS {trigger}")
                connection.execute(
                    f"CREATE TRIGGER {trigger} BEFORE DELETE ON {table} "
                    f"WHEN NOT EXISTS(SELECT 1 FROM account_deletion_requests WHERE {condition}) "
                    "BEGIN SELECT RAISE(ABORT, 'immutable records can only be removed with their account'); END"
                )
            connection.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (8, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))")
    connection.execute("CREATE TABLE IF NOT EXISTS generation_branch_guards (branch_id TEXT PRIMARY KEY REFERENCES branches(id) ON DELETE CASCADE, generation_job_id TEXT NOT NULL REFERENCES generation_jobs(id) ON DELETE CASCADE, acquired_at TEXT NOT NULL)")
    connection.execute("CREATE TABLE IF NOT EXISTS generation_events (id INTEGER PRIMARY KEY AUTOINCREMENT, generation_job_id TEXT NOT NULL REFERENCES generation_jobs(id) ON DELETE CASCADE, stage TEXT, event_type TEXT NOT NULL, offset INTEGER, content TEXT NOT NULL DEFAULT '', payload_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_generation_events_job ON generation_events(generation_job_id, id)")
    connection.execute("CREATE TABLE IF NOT EXISTS execution_epochs (id INTEGER PRIMARY KEY CHECK(id = 1), epoch TEXT NOT NULL, created_at TEXT NOT NULL)")
    connection.execute("INSERT OR IGNORE INTO execution_epochs(id, epoch, created_at) VALUES (1, lower(hex(randomblob(16))), strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))")


def request_connection(request: Request):
    connection = connect(request.app.state.database_url)
    try:
        yield connection
    finally:
        connection.close()


@contextmanager
def transaction(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield connection
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()


def assert_branch_mutable(connection: sqlite3.Connection, branch_id: str) -> None:
    """Reject effective story mutations while a generation owns the branch."""
    try:
        row = connection.execute("SELECT generation_job_id FROM generation_branch_guards WHERE branch_id=?", (branch_id,)).fetchone()
    except sqlite3.OperationalError:
        return
    if row is not None:
        raise StateConflict("Branch is locked by an active generation")
