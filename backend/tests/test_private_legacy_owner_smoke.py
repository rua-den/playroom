"""Exercise private-owner disposable-SQLite smoke with only synthetic fixture."""
from private_legacy_owner_smoke import run_private_legacy_smoke
from test_legacy_156_scale import _scale_bundle


def test_disposable_legacy_acceptance_156_scale_and_no_fabricated_turns():
    result = run_private_legacy_smoke(_scale_bundle())
    assert result["status"] == "PASS"
    assert result["characters"] == 36
    assert result["approved_memory_records"] == 68
    assert result["actual_transcript_turns"] == 0
    assert result["review_before_approval_blocked"] is True
    assert result["approved_state_persisted_after_reopen"] is True
    assert result["repeat_import_idempotent"] is True
    assert result["next_chapter"] == 157
