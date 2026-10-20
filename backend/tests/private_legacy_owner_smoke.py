"""Owner-local Legacy bundle acceptance in disposable SQLite, no model calls.

Usage:
    PYTHONPATH=backend python backend/tests/private_legacy_owner_smoke.py /private/path/story.json

The private source stays on the operator's own machine. Do not upload it to
public GitHub, attach it to a CI job, or print private story prose.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from uuid import uuid4

from playroom.auth import create_owner
from playroom.chatgpt_import import (
    approve_import_review, assert_import_review_approved, import_review,
)
from playroom.db import connect, migrate
from playroom.domain import StateConflict
from playroom.legacy_import import import_legacy_bundle, preview_legacy_bundle
from playroom.timeline import get_branch_head


def run_private_legacy_smoke(source: dict) -> dict:
    """Use the real Playroom importer; never send provider requests or retain DB."""
    report = preview_legacy_bundle(source)
    count = report["counts"]
    total = count["canon_facts"] + count["timeline_events"] + count["relationships"]
    with tempfile.TemporaryDirectory(prefix="playroom-private-legacy-") as temp:
        db_path = Path(temp) / "test.sqlite3"
        conn = connect(db_path)
        try:
            migrate(conn)
            owner = create_owner(conn, "private-acceptance@example.test", "synthetic-test-password-only")
            owner_id = owner.id
            key = str(uuid4())
            staged = import_legacy_bundle(conn, owner_id, source, key)
            campaign_id, branch_id = staged["campaign_id"], staged["branch_id"]
            assert staged["turn_count"] == 0
            assert staged["pending_memories"] == total
            assert staged["review_required"] is True
            assert conn.execute(
                "SELECT COUNT(*) FROM turns WHERE campaign_id=?", (campaign_id,)
            ).fetchone()[0] == 0
            same_key = import_legacy_bundle(conn, owner_id, source, key)
            assert same_key["already_imported"] is True
            assert same_key["campaign_id"] == campaign_id
            head = get_branch_head(conn, campaign_id, branch_id, owner_id)
            locked = False
            try:
                assert_import_review_approved(conn, owner_id, campaign_id, head.checkpoint_id)
            except StateConflict:
                locked = True
            assert locked, "Legacy review gate was not enforced"
            approved = approve_import_review(
                conn, owner_id, campaign_id, branch_id, head.checkpoint_id,
                {"persona": True, "npc_voice_presence": True,
                 "canon_known_by_narrator_only": True, "missing_history": True,
                 "provider_data": True},
            )
            assert approved["required"] is False
        finally:
            conn.close()
        reopened = connect(db_path)
        try:
            migrate(reopened)
            head_after = get_branch_head(reopened, campaign_id, branch_id, owner_id)
            assert_import_review_approved(
                reopened, owner_id, campaign_id, head_after.checkpoint_id
            )
            assert import_review(reopened, owner_id, campaign_id)["required"] is False
            approved_memories = reopened.execute(
                "SELECT COUNT(DISTINCT memory_id) FROM memory_versions "
                "WHERE campaign_id=? AND status='approved' AND origin='import'",
                (campaign_id,),
            ).fetchone()[0]
            assert approved_memories == total
            assert reopened.execute(
                "SELECT COUNT(*) FROM campaigns"
            ).fetchone()[0] == 1
            assert reopened.execute(
                "SELECT COUNT(*) FROM turns WHERE campaign_id=?", (campaign_id,)
            ).fetchone()[0] == 0
            no_duplicate = import_legacy_bundle(reopened, owner_id, source, str(uuid4()))
            assert no_duplicate["already_imported"] is True
            assert no_duplicate["campaign_id"] == campaign_id
        finally:
            reopened.close()
    return {
        "status": "PASS",
        "mode": "private_disposable_sqlite_no_provider",
        "characters": count["characters"],
        "canon_facts": count["canon_facts"],
        "timeline_events": count["timeline_events"],
        "relationships": count["relationships"],
        "approved_memory_records": total,
        "actual_transcript_turns": 0,
        "review_before_approval_blocked": True,
        "approved_state_persisted_after_reopen": True,
        "repeat_import_idempotent": True,
        "next_chapter": report["checkpoint"]["next_chapter"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Private Legacy import acceptance")
    parser.add_argument("bundle", type=Path, help="Private local legacy JSON path")
    parser.add_argument("--report", type=Path, help="Optional private report path")
    args = parser.parse_args()
    try:
        source = json.loads(args.bundle.read_text(encoding="utf-8"))
        outcome = run_private_legacy_smoke(source)
    except Exception as exc:
        # Neither raw source nor private exception messages belong in logs.
        outcome = {"status": "FAIL", "failure_kind": type(exc).__name__,
                   "mode": "private_disposable_sqlite_no_provider"}
    rendered = json.dumps(outcome, indent=2, ensure_ascii=False)
    if args.report is not None:
        args.report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    raise SystemExit(0 if outcome["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
