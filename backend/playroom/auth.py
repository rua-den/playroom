from __future__ import annotations

import argparse
import hashlib
import getpass
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from .db import connect, migrate, transaction
from .domain import NotFound, Owner, RateLimited, StateConflict, Unauthorized, ValidationError
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


def _normalize_identity(identity: str) -> str:
    normalized = identity.strip().casefold()
    if not normalized or len(normalized) > 254:
        raise ValidationError("A username or email is required")
    return normalized


def _normalize_username(username: str) -> str:
    normalized = username.strip().casefold()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,30}[a-z0-9]", normalized):
        raise ValidationError("Username must be 3–32 letters, numbers, dots, underscores, or hyphens")
    return normalized


def _username_email(username: str) -> str:
    return f"{username}@account.playroom.invalid"


def _insert_owner(connection: sqlite3.Connection, email: str, username: str, password: str, *, is_admin: bool, minimum_password_length: int = 12) -> Owner:
    if len(password) < minimum_password_length:
        raise ValidationError(f"Owner password must contain at least {minimum_password_length} characters")
    owner_id = str(uuid4())
    try:
        connection.execute(
            "INSERT INTO owners(id, email, username, is_admin, password_hash, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (owner_id, email, username, int(is_admin), PASSWORDS.hash(password), utc_now()),
        )
    except sqlite3.IntegrityError as exc:
        raise ValidationError("An account with this username already exists") from exc
    return Owner(owner_id, email, username, is_admin)


def create_owner(connection: sqlite3.Connection, email: str, password: str, *, is_admin: bool = False) -> Owner:
    email = _normalize_email(email)
    return _insert_owner(connection, email, email, password, is_admin=is_admin)


def create_account(connection: sqlite3.Connection, username: str, password: str) -> Owner:
    username = _normalize_username(username)
    return _insert_owner(connection, _username_email(username), username, password, is_admin=False)


def create_test_admin(connection: sqlite3.Connection) -> Owner | None:
    """Create the deliberately weak admin/admin account only in explicit local test setup."""
    with transaction(connection):
        if connection.execute("SELECT 1 FROM owners LIMIT 1").fetchone() is not None:
            return None
        return _insert_owner(connection, _username_email("admin"), "admin", "admin", is_admin=True, minimum_password_length=1)


def update_account(connection: sqlite3.Connection, owner_id: str, username: str, password: str | None, *, actor_id: str, session_token: str) -> Owner:
    username = _normalize_username(username)
    if password == "":
        password = None
    if password is not None and len(password) < 12:
        raise ValidationError("Account password must contain at least 12 characters")
    row = connection.execute("SELECT id FROM owners WHERE id=?", (owner_id,)).fetchone()
    if row is None:
        raise NotFound("Account not found")
    try:
        if password is None:
            connection.execute("UPDATE owners SET username=?, email=? WHERE id=?", (username, _username_email(username), owner_id))
        else:
            connection.execute("UPDATE owners SET username=?, email=?, password_hash=? WHERE id=?", (username, _username_email(username), PASSWORDS.hash(password), owner_id))
    except sqlite3.IntegrityError as exc:
        raise ValidationError("An account with this username already exists") from exc
    if password is not None:
        token_hash = hashlib.sha256(session_token.encode("utf-8")).hexdigest() if owner_id == actor_id else ""
        connection.execute("UPDATE sessions SET revoked_at=? WHERE owner_id=? AND revoked_at IS NULL AND token_hash<>?", (utc_now(), owner_id, token_hash))
    updated = connection.execute("SELECT id,email,username,is_admin FROM owners WHERE id=?", (owner_id,)).fetchone()
    return Owner(updated["id"], updated["email"], updated["username"], bool(updated["is_admin"]))


def delete_account(connection: sqlite3.Connection, owner_id: str, *, actor_id: str) -> None:
    if owner_id == actor_id:
        raise StateConflict("You cannot delete your own account")
    if connection.execute("SELECT 1 FROM owners WHERE id=?", (owner_id,)).fetchone() is None:
        raise NotFound("Account not found")
    if connection.execute("SELECT 1 FROM generation_jobs WHERE owner_id=? AND status IN ('queued','running','cancelling','interrupted') LIMIT 1", (owner_id,)).fetchone() is not None:
        raise StateConflict("Cancel or recover active generation jobs before deleting this account")
    connection.execute("INSERT INTO account_deletion_requests(owner_id,campaign_id) VALUES (?,NULL)", (owner_id,))
    connection.execute("INSERT INTO account_deletion_requests(owner_id,campaign_id) SELECT owner_id,id FROM campaigns WHERE owner_id=?", (owner_id,))
    connection.execute("DELETE FROM owners WHERE id=?", (owner_id,))
    connection.execute("DELETE FROM account_deletion_requests WHERE owner_id=?", (owner_id,))


def verify_owner_password(connection: sqlite3.Connection, email: str, password: str, *, failure_limit: int = 5, window_seconds: int = 900) -> Owner:
    email = _normalize_identity(email)
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(seconds=window_seconds)).isoformat().replace("+00:00", "Z")
    failures = connection.execute("SELECT COUNT(*) FROM login_failures WHERE email = ? AND failed_at >= ?", (email, cutoff)).fetchone()[0]
    if failures >= failure_limit:
        raise RateLimited("Too many failed login attempts")
    owner = connection.execute("SELECT id, email, username, is_admin, password_hash FROM owners WHERE email = ? COLLATE NOCASE OR username = ? COLLATE NOCASE LIMIT 1", (email, email)).fetchone()
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
    return Owner(owner["id"], owner["email"], owner["username"], bool(owner["is_admin"]))


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
        "SELECT o.id, o.email, o.username, o.is_admin FROM sessions s JOIN owners o ON o.id = s.owner_id WHERE s.token_hash = ? AND s.revoked_at IS NULL AND s.expires_at > ?",
        (token_hash, now_text),
    ).fetchone()
    return Owner(row["id"], row["email"], row["username"], bool(row["is_admin"])) if row else None


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
        is_first_owner = connection.execute("SELECT 1 FROM owners LIMIT 1").fetchone() is None
        owner = create_owner(connection, args.email, password, is_admin=is_first_owner)
        print(f"Created owner {owner.email} ({owner.id})")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
