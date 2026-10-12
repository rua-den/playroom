from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import unquote, urlsplit

from fastapi import Request


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


def migrate(connection: sqlite3.Connection) -> None:
    migration = Path(__file__).parent / "migrations" / "001_initial.sql"
    connection.executescript(migration.read_text(encoding="utf-8"))
    columns = {row[1] for row in connection.execute("PRAGMA table_info(campaigns)")}
    if "archived_at" not in columns:
        connection.execute("ALTER TABLE campaigns ADD COLUMN archived_at TEXT")
    generation_columns = {row[1] for row in connection.execute("PRAGMA table_info(generation_jobs)")}
    if generation_columns:
        for name, definition in (("action", "TEXT NOT NULL DEFAULT ''"), ("mode", "TEXT NOT NULL DEFAULT 'economy'"), ("policy", "TEXT NOT NULL DEFAULT 'free_only'"), ("draft", "TEXT NOT NULL DEFAULT ''"), ("failure_json", "TEXT"), ("usage_json", "TEXT")):
            if name not in generation_columns:
                connection.execute(f"ALTER TABLE generation_jobs ADD COLUMN {name} {definition}")
    attempt_columns = {row[1] for row in connection.execute("PRAGMA table_info(provider_attempts)")}
    if attempt_columns and "output_text" not in attempt_columns:
        connection.execute("ALTER TABLE provider_attempts ADD COLUMN output_text TEXT NOT NULL DEFAULT ''")


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
