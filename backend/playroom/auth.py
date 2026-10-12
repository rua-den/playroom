from __future__ import annotations

import argparse
import hashlib
import getpass
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from .db import connect, migrate, transaction
from .domain import Owner, RateLimited, Unauthorized, ValidationError
from .timeline import utc_now

SESSION_COOKIE = "playroom_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 14
PASSWORDS = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1, type=Type.ID)
_DUMMY_PASSWORD_HASH = PASSWORDS.hash("not-a-real-owner-password")


def _normalize_email(email: str) -> str:
    normalized = email.strip().casefold()
    if not normalized or "@" not in normalized or len(normalized) > 254:
        raise ValidationError("A valid email address is required")
    return normalized


def create_owner(connection: sqlite3.Connection, email: str, password: str) -> Owner:
    email = _normalize_email(email)
    if len(password) < 12:
        raise ValidationError("Owner password must contain at least 12 characters")
    owner_id = str(uuid4())
    try:
        connection.execute("INSERT INTO owners(id, email, password_hash, created_at) VALUES (?, ?, ?, ?)", (owner_id, email, PASSWORDS.hash(password), utc_now()))
    except sqlite3.IntegrityError as exc:
        raise ValidationError("An owner with this email already exists") from exc
    return Owner(owner_id, email)


def verify_owner_password(connection: sqlite3.Connection, email: str, password: str, *, failure_limit: int = 5, window_seconds: int = 900) -> Owner:
    email = _normalize_email(email)
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(seconds=window_seconds)).isoformat().replace("+00:00", "Z")
    failures = connection.execute("SELECT COUNT(*) FROM login_failures WHERE email = ? AND failed_at >= ?", (email, cutoff)).fetchone()[0]
    if failures >= failure_limit:
        raise RateLimited("Too many failed login attempts")
    owner = connection.execute("SELECT id, email, password_hash FROM owners WHERE email = ?", (email,)).fetchone()
    password_hash = owner["password_hash"] if owner else _DUMMY_PASSWORD_HASH
    try:
        password_matches = PASSWORDS.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        password_matches = False
    if owner is None or not password_matches:
        with transaction(connection):
            connection.execute("DELETE FROM login_failures WHERE failed_at < ?", (cutoff,))
            connection.execute("INSERT INTO login_failures(email, failed_at) VALUES (?, ?)", (email, utc_now()))
        raise Unauthorized("Email or password is incorrect")
    with transaction(connection):
        connection.execute("DELETE FROM login_failures WHERE email = ?", (email,))
    if PASSWORDS.check_needs_rehash(owner["password_hash"]):
        connection.execute("UPDATE owners SET password_hash = ? WHERE id = ?", (PASSWORDS.hash(password), owner["id"]))
    return Owner(owner["id"], owner["email"])


def create_session(connection: sqlite3.Connection, owner_id: str, *, ttl_seconds: int = SESSION_TTL_SECONDS) -> str:
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)
    connection.execute(
        "INSERT INTO sessions(id, owner_id, token_hash, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
        (str(uuid4()), owner_id, token_hash, now.isoformat().replace("+00:00", "Z"), (now + timedelta(seconds=ttl_seconds)).isoformat().replace("+00:00", "Z")),
    )
    return raw_token


def session_valid(connection: sqlite3.Connection, raw_token: str | None, *, now: datetime | None = None) -> Owner | None:
    if not raw_token or len(raw_token) > 256:
        return None
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    now_text = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    row = connection.execute(
        "SELECT o.id, o.email FROM sessions s JOIN owners o ON o.id = s.owner_id WHERE s.token_hash = ? AND s.revoked_at IS NULL AND s.expires_at > ?",
        (token_hash, now_text),
    ).fetchone()
    return Owner(row["id"], row["email"]) if row else None


def revoke_session(connection: sqlite3.Connection, raw_token: str | None) -> None:
    if not raw_token or len(raw_token) > 256:
        return
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    connection.execute("UPDATE sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL", (utc_now(), token_hash))


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage the private Playroom owner account")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create-owner", help="Create the single owner account without a public registration route")
    create.add_argument("--database-url", required=True, help="SQLite URL or database path")
    create.add_argument("--email", required=True)
    args = parser.parse_args()
    password = getpass.getpass("Owner password (minimum 12 characters): ")
    confirmation = getpass.getpass("Confirm owner password: ")
    if password != confirmation:
        parser.error("Passwords do not match")
    connection = connect(args.database_url)
    try:
        migrate(connection)
        owner = create_owner(connection, args.email, password)
        print(f"Created owner {owner.email} ({owner.id})")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
