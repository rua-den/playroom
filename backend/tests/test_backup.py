import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from playroom.app import create_app
from playroom.auth import create_owner, create_session, session_valid
from playroom.backup import backup_database, main, restore_database
from playroom.campaigns import create_campaign
from playroom.db import connect, migrate
from playroom.domain import ValidationError
from playroom.generation import GenerationService
from playroom.provider import FakeProvider
from playroom.timeline import get_branch_head


@pytest.fixture
def story(tmp_path):
    source = tmp_path / "source.sqlite3"
    db = connect(source)
    migrate(db)
    owner = create_owner(db, "backup@example.test", "synthetic backup password")
    campaign = create_campaign(db, owner.id, "Synthetic backup", {"name": "World"}, [], {"name": "Player"})
    yield source, db, owner, campaign
    db.close()


def rows(db, table):
    return [tuple(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY rowid")]


def test_live_wal_roundtrip_preserves_history_and_leaves_source_unchanged(story, tmp_path):
    source, db, owner, campaign = story
    service = GenerationService(db, FakeProvider(["Rain falls."]))
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    job = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Listen", idempotency_key="one", expected_checkpoint_id=head.checkpoint_id)
    service.commit_candidate(owner.id, job["id"])
    db.execute("INSERT INTO legacy_import_sources VALUES('source',?,?,?,'import','hash','{\"synthetic_excerpt\":\"Rain falls.\"}','[]',0,0,1,'now')", (owner.id, campaign.id, campaign.initial_branch_id))
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    (secrets / "fixture-key.json").write_text('"synthetic secret excluded from backup"')
    assert Path(str(source) + "-wal").stat().st_size > 0
    tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name<>'execution_epochs'")]
    before = {table: rows(db, table) for table in tables}
    snapshot = tmp_path / "snapshot.sqlite3"
    backup_database(source, snapshot)
    restored = restore_database(snapshot, tmp_path / "restored")
    with sqlite3.connect(restored) as copy:
        assert {table: rows(copy, table) for table in tables} == before
        assert copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert {table: rows(db, table) for table in tables} == before
    assert list((tmp_path / "restored").iterdir()) == [restored]


@pytest.mark.parametrize("status", ["queued", "running", "cancelling", "candidate", "interrupted"])
def test_restore_revokes_authority_and_cannot_resume_or_commit_jobs(story, tmp_path, status):
    source, db, owner, campaign = story
    token = create_session(db, owner.id)
    service = GenerationService(db, FakeProvider([]))
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    job = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Listen", idempotency_key="pending", expected_checkpoint_id=head.checkpoint_id, execute=False)
    db.execute("UPDATE generation_jobs SET status=?,draft='Synthetic draft',reserved_cost_json=? WHERE id=?", (status, '{"total_usd":"0.01"}', job["id"]))
    for index, attempt_status in enumerate(["queued", "claimed", "dispatched"]):
        db.execute("INSERT INTO provider_attempts(id,generation_job_id,stage,stage_key,profile_snapshot_json,payload_hash,status,created_at) VALUES(?,?,'narration',?,'{}','hash',?,'now')", (f"attempt-{index}", job["id"], f"key-{index}", attempt_status))
    db.execute("INSERT INTO paid_trial_authorizations VALUES('grant',?,'profile',1,'1','0.1',10,'2099-01-01','active','now')", (owner.id,))
    db.execute("INSERT INTO paid_trial_reservations VALUES(?,'grant','0.01','now')", (job["id"],))
    epoch = db.execute("SELECT epoch FROM execution_epochs").fetchone()[0]
    snapshot = tmp_path / "snapshot.sqlite3"
    backup_database(source, snapshot)
    restored = restore_database(snapshot, tmp_path / "restored")
    copy = connect(restored)
    assert session_valid(copy, token) is None
    assert copy.execute("SELECT state FROM paid_trial_authorizations").fetchone()[0] == "revoked"
    assert copy.execute("SELECT epoch FROM execution_epochs").fetchone()[0] != epoch
    assert rows(copy, "paid_trial_reservations") == rows(db, "paid_trial_reservations")
    assert not rows(copy, "generation_branch_guards")
    assert {row[0] for row in copy.execute("SELECT status FROM provider_attempts")} == {"interrupted"}
    provider = FakeProvider([])
    app = create_app(str(restored), generation_provider=provider, credential_root=str(tmp_path / "restored" / "secrets"), allowed_hosts={"testserver"})
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        recovered = GenerationService(copy, provider).get_job(owner.id, job["id"])
        assert recovered["status"] == "interrupted"
        assert recovered["draft"] == "Synthetic draft"
        assert recovered["failure"]["code"] == "RESTORED_SNAPSHOT"
        assert recovered["reserved_cost_json"] == '{"total_usd":"0.01"}'
        with pytest.raises(ValidationError, match="complete candidate"):
            GenerationService(copy, provider).commit_candidate(owner.id, job["id"])
        assert not rows(copy, "turns")
    assert provider.calls == []
    assert db.execute("SELECT status FROM generation_jobs").fetchone()[0] == status
    assert session_valid(db, token) is not None
    copy.close()


def test_refuses_overwrites_and_invalid_sources_without_leaving_restore(tmp_path, story):
    source, _, _, _ = story
    output = tmp_path / "existing.sqlite3"
    output.write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        backup_database(source, output)
    assert output.read_bytes() == b"keep"
    directory = tmp_path / "existing"
    directory.mkdir()
    with pytest.raises(FileExistsError):
        restore_database(source, directory)
    for contents in [b"not sqlite", b""]:
        invalid = tmp_path / "invalid.sqlite3"
        invalid.write_bytes(contents)
        with pytest.raises((ValueError, sqlite3.DatabaseError)):
            restore_database(invalid, tmp_path / "bad-restore")
        assert not (tmp_path / "bad-restore").exists()
    with pytest.raises(FileNotFoundError):
        backup_database(tmp_path / "missing.sqlite3", tmp_path / "missing-backup.sqlite3")
    assert not (tmp_path / "missing.sqlite3").exists()
    unrelated = tmp_path / "unrelated.sqlite3"
    with sqlite3.connect(unrelated) as other:
        other.execute("CREATE TABLE unrelated(value)")
    with pytest.raises(ValueError, match="supported Playroom"):
        restore_database(unrelated, tmp_path / "bad-restore")
    assert not (tmp_path / "bad-restore").exists()
    assert not list(tmp_path.glob(".playroom-backup-*"))


def test_cli_roundtrip(story, tmp_path, capsys):
    source, _, _, _ = story
    snapshot = tmp_path / "cli.sqlite3"
    directory = tmp_path / "cli-restored"
    assert main(["backup", "--database", str(source), "--output", str(snapshot)]) == 0
    assert main(["restore", "--database", str(snapshot), "--data-directory", str(directory)]) == 0
    assert (directory / "playroom.sqlite3").is_file()
    assert "Provider secrets are excluded" in capsys.readouterr().out


def test_refuses_symlink_destinations(story, tmp_path):
    source, _, _, _ = story
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("Host cannot create directory symlinks")
    with pytest.raises(ValueError, match="link"):
        backup_database(source, link / "snapshot.sqlite3")
    with pytest.raises(ValueError, match="link"):
        restore_database(source, link / "restored")
    assert list(target.iterdir()) == []
