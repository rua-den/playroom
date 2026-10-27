from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from playroom.db import _add_column_if_missing, connect, migrate


def test_add_column_if_missing_propagates_unrelated_sqlite_errors():
    class FailingConnection:
        def execute(self, sql, parameters=()):
            raise sqlite3.OperationalError("database is locked")

    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        _add_column_if_missing(FailingConnection(), "owners", "extra", "TEXT")


def test_add_column_if_missing_propagates_duplicate_when_column_is_absent():
    class DuplicateConnection:
        def execute(self, sql, parameters=()):
            if sql.startswith("ALTER TABLE"):
                raise sqlite3.OperationalError("duplicate column name: extra")
            return []

    with pytest.raises(sqlite3.OperationalError, match="duplicate column name"):
        _add_column_if_missing(DuplicateConnection(), "owners", "extra", "TEXT")


def test_migrate_adds_nullable_roleplay_columns_without_backfilling_legacy_rows(tmp_path):
    db = connect(tmp_path / "legacy.sqlite3")
    initial = Path(__file__).parents[1] / "playroom" / "migrations" / "001_initial.sql"
    db.executescript(initial.read_text(encoding="utf-8"))

    owner_id, campaign_id, branch_id = str(uuid4()), str(uuid4()), str(uuid4())
    turn_id, revision_id = str(uuid4()), str(uuid4())
    now = "2026-10-13T00:00:00Z"
    db.execute("INSERT INTO owners(id,email,password_hash,created_at) VALUES(?,?,?,?)", (owner_id, "legacy@example.test", "hash", now))
    db.execute("INSERT INTO campaigns(id,owner_id,title,created_at,updated_at) VALUES(?,?,?,?,?)", (campaign_id, owner_id, "Legacy", now, now))
    db.execute("INSERT INTO branches(id,campaign_id,name,state_version,created_at) VALUES(?,?,?,?,?)", (branch_id, campaign_id, "main", 0, now))
    db.execute("INSERT INTO turns(id,campaign_id,branch_id,sequence,action_text,created_at) VALUES(?,?,?,?,?,?)", (turn_id, campaign_id, branch_id, 1, "Legacy action", now))
    db.execute("INSERT INTO turn_revisions(id,turn_id,revision,narrative_text,complete,selected,created_at) VALUES(?,?,?,?,?,?,?)", (revision_id, turn_id, 1, "Legacy narrative", 1, 1, now))

    migrate(db)

    turn_columns = {row[1] for row in db.execute("PRAGMA table_info(turns)")}
    revision_columns = {row[1] for row in db.execute("PRAGMA table_info(turn_revisions)")}
    assert "input_segments_json" in turn_columns
    assert "output_segments_json" in revision_columns
    legacy = db.execute("SELECT action_text,input_segments_json FROM turns WHERE id=?", (turn_id,)).fetchone()
    legacy_revision = db.execute("SELECT narrative_text,output_segments_json FROM turn_revisions WHERE id=?", (revision_id,)).fetchone()
    assert legacy["action_text"] == "Legacy action"
    assert legacy["input_segments_json"] is None
    assert legacy_revision["narrative_text"] == "Legacy narrative"
    assert legacy_revision["output_segments_json"] is None
    db.close()


def test_migrate_backfills_existing_owner_as_admin_once(tmp_path):
    db = connect(tmp_path / "legacy-account.sqlite3")
    initial = Path(__file__).parents[1] / "playroom" / "migrations" / "001_initial.sql"
    db.executescript(initial.read_text(encoding="utf-8"))
    owner_id = str(uuid4())
    db.execute("INSERT INTO owners(id,email,password_hash,created_at) VALUES(?,?,?,?)", (owner_id, "legacy@example.test", "hash", "2026-10-13T00:00:00Z"))

    migrate(db)
    owner = db.execute("SELECT username,is_admin FROM owners WHERE id=?", (owner_id,)).fetchone()
    assert (owner["username"], owner["is_admin"]) == ("legacy@example.test", 1)

    db.execute("UPDATE owners SET is_admin=0 WHERE id=?", (owner_id,))
    migrate(db)
    assert db.execute("SELECT is_admin FROM owners WHERE id=?", (owner_id,)).fetchone()[0] == 0
    db.close()
