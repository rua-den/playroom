"""Owner-local SQLite snapshots; provider secret files are deliberately excluded."""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from uuid import uuid4


def _plain_path(value: str | Path) -> Path:
    path = Path(value).absolute()
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise ValueError("Database paths must not traverse symbolic links or junctions")
    return path


def _validate(db: sqlite3.Connection) -> None:
    if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise ValueError("SQLite integrity check failed")
    if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ValueError("SQLite foreign key check failed")
    required = {"owners", "campaigns", "branches", "profile_versions", "turns", "turn_revisions", "state_checkpoints", "sessions", "generation_jobs", "provider_attempts", "generation_branch_guards", "execution_epochs", "paid_trial_authorizations", "paid_trial_reservations"}
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not required <= tables:
        raise ValueError("Not a supported Playroom database; upgrade the source app before backing up")
    # Check the recovery fields before publishing a backup we cannot safely restore.
    for query in (
        "SELECT revoked_at FROM sessions LIMIT 0",
        "SELECT status,failure_json,cancel_requested,execution_epoch FROM generation_jobs LIMIT 0",
        "SELECT status,failure_json,finished_at,cancel_requested FROM provider_attempts LIMIT 0",
        "SELECT state FROM paid_trial_authorizations LIMIT 0",
        "SELECT epoch,created_at FROM execution_epochs WHERE id=1",
    ):
        db.execute(query)
    if db.execute("SELECT count(*) FROM execution_epochs WHERE id=1").fetchone()[0] != 1:
        raise ValueError("Missing Playroom execution epoch")


@contextmanager
def _snapshot(source: Path, parent: Path):
    if not source.is_file():
        raise FileNotFoundError("Source database must be an existing regular file")
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
        _validate(original)
        descriptor, name = tempfile.mkstemp(prefix=".playroom-backup-", suffix=".sqlite3", dir=parent)
        os.close(descriptor)
        temporary = Path(name)
        try:
            with closing(sqlite3.connect(temporary)) as copy:
                original.backup(copy)
                copy.execute("PRAGMA journal_mode=DELETE")
                _validate(copy)
            yield temporary
        finally:
            temporary.unlink(missing_ok=True)


def backup_database(database: str | Path, output: str | Path) -> Path:
    source, destination = _plain_path(database), _plain_path(output)
    if destination.exists():
        raise FileExistsError("Backup output already exists")
    with _snapshot(source, destination.parent) as temporary:
        # A hard link publishes complete bytes atomically and refuses an existing target.
        os.link(temporary, destination)
    return destination


def restore_database(database: str | Path, data_directory: str | Path) -> Path:
    source, directory = _plain_path(database), _plain_path(data_directory)
    if directory.exists():
        raise FileExistsError("Restore requires a new data directory")
    # Validate and sanitize privately before creating the visible restore directory.
    with _snapshot(source, directory.parent) as temporary:
        now = datetime.now(timezone.utc).isoformat()
        failure = json.dumps({"code": "RESTORED_SNAPSHOT", "message": "Restored snapshot: generation interrupted; review the preserved draft before a new Send."})
        with closing(sqlite3.connect(temporary)) as restored:
            with restored:
                restored.execute("UPDATE sessions SET revoked_at=? WHERE revoked_at IS NULL", (now,))
                restored.execute("UPDATE paid_trial_authorizations SET state='revoked' WHERE state='active'")
                restored.execute("UPDATE execution_epochs SET epoch=?,created_at=? WHERE id=1", (str(uuid4()), now))
                restored.execute("UPDATE generation_jobs SET status='interrupted',failure_json=?,cancel_requested=1 WHERE status NOT IN ('committed','failed','cancelled')", (failure,))
                restored.execute("UPDATE provider_attempts SET status='interrupted',failure_json=?,finished_at=?,cancel_requested=1 WHERE status IN ('queued','claimed','dispatched')", (failure, now))
                restored.execute("DELETE FROM generation_branch_guards")
            _validate(restored)
        directory.mkdir(mode=0o700)
        destination = directory / "playroom.sqlite3"
        try:
            os.link(temporary, destination)
        except BaseException:
            directory.rmdir()
            raise
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("backup", help="Snapshot an existing SQLite database, including live WAL data")
    backup.add_argument("--database", type=Path, required=True)
    backup.add_argument("--output", type=Path, required=True)
    restore = commands.add_parser("restore", help="Restore into a NEW data directory; revoke sessions and paid grants")
    restore.add_argument("--database", type=Path, required=True, help="Snapshot file")
    restore.add_argument("--data-directory", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        destination = backup_database(args.database, args.output) if args.command == "backup" else restore_database(args.database, args.data_directory)
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.exit(1, f"Backup/restore failed: {exc}\n")
    print(f"Created {destination}. Provider secrets are excluded; keep this private story database secure.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
