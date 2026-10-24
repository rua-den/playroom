import json
from decimal import Decimal

import pytest

from local_story_quality_trial import (
    APPROVAL, ENDPOINT, MAX_INPUT_BYTES, MAX_OUTPUT, MAX_POSTS, MAX_USD, MODEL,
    PER_SEND, DispatchGuard, OfflineTransport, balance_preflight, run_trial,
)


def test_default_offline_persists_twenty_turns_and_midpoint_context(tmp_path, monkeypatch):
    monkeypatch.setenv('ollama_key', 'must-not-be-used')
    monkeypatch.setattr('local_story_quality_trial.read_local_key', lambda: pytest.fail('offline read key'))
    root = tmp_path / 'run'
    report = run_trial(root)
    assert report['status'] == 'completed'
    assert report['provider_posts'] == report['committed_turns'] == MAX_POSTS == 20
    assert report['quality_verdict'] == 'needs human review'
    assert report['persisted_grants'] == 1 and report['persisted_reservations'] == 20
    assert Decimal(report['reserved_usd']) <= MAX_USD <= Decimal('.20')
    assert report['usage']['input_tokens'] == 2000
    assert report['usage']['output_tokens'] == 2400
    assert report['estimated_usage_usd'] != report['reserved_usd']
    assert report['turns'][10]['summary_selected'] and report['turns'][10]['courtyard_selected']
    assert (root / 'data' / 'playroom.sqlite3').exists()
    assert json.loads((root / 'report.json').read_text(encoding='utf-8')) == report
    with pytest.raises(FileExistsError):
        run_trial(root)


@pytest.mark.parametrize('failure,code', [('malformed', 'SCHEMA_INVALID'), ('truncated', 'OUTPUT_TRUNCATED'), ('agency', 'PLAYER_AGENCY_VIOLATION'), ('knowledge', 'NPC_KNOWLEDGE_VIOLATION'), ('known_other', 'NPC_KNOWLEDGE_VIOLATION'), ('grounding', 'UNGROUNDED_PRECISION')])
def test_failed_turn_preserves_evidence_without_retry(tmp_path, failure, code):
    report = run_trial(tmp_path / failure, transport=OfflineTransport(failure))
    assert report['status'] == 'stopped' and report['provider_posts'] == 1
    assert report['committed_turns'] == 0 and report['failure_code'] == code
    assert report['turns'][0]['job_id'] and 'failed_draft' in report['turns'][0]
    assert report['turns'][0]['failed_provider_output']
    assert len(report['turns'][0]['failed_provider_output']) <= MAX_OUTPUT * 8


def test_absent_npc_cannot_supply_dialogue(tmp_path):
    report = run_trial(tmp_path / 'absent', transport=OfflineTransport('absent'))
    assert report['status'] == 'stopped' and report['provider_posts'] == 1
    assert report['committed_turns'] == 0


def test_redirect_and_failed_balance_never_dispatch(tmp_path):
    def deny():
        raise RuntimeError('balance unavailable')
    guard = DispatchGuard(tmp_path, deny)
    wire = {'model': MODEL, 'max_tokens': MAX_OUTPUT}
    with pytest.raises(RuntimeError, match='URL'):
        guard.check('POST', 'https://other.invalid/chat/completions', wire)
    with pytest.raises(RuntimeError, match='balance'):
        guard.check('POST', ENDPOINT + '/chat/completions', wire)
    assert guard.provider_posts == 0 and guard.path.read_text() == ''


def test_live_requires_separate_approval_before_reading_key_or_creating_state(tmp_path, monkeypatch):
    monkeypatch.setattr('local_story_quality_trial.read_local_key', lambda: pytest.fail('read secret'))
    with pytest.raises(RuntimeError, match='approval'):
        run_trial(tmp_path / 'live', live=True, approval='old')
    assert not (tmp_path / 'live').exists()
    assert APPROVAL == 'OWNER_LOCAL_STORY_QUALITY_2026_10_24'


def test_dispatch_guard_persists_before_each_post_and_bounds_reuse(tmp_path):
    checks = []
    guard = DispatchGuard(tmp_path, lambda: checks.append(True))
    wire = {'model': MODEL, 'max_tokens': MAX_OUTPUT, 'messages': []}
    for _ in range(MAX_POSTS):
        guard.check('POST', ENDPOINT + '/chat/completions', wire)
    with pytest.raises(RuntimeError):
        guard.check('POST', ENDPOINT + '/chat/completions', wire)
    assert len(checks) == len((tmp_path / 'dispatches.jsonl').read_text().splitlines()) == 20
    with pytest.raises(FileExistsError):
        DispatchGuard(tmp_path, lambda: None)


@pytest.mark.parametrize('change', [{'model': 'other'}, {'max_tokens': True}, {'max_tokens': MAX_OUTPUT + 1}, {'messages': ['x' * MAX_INPUT_BYTES]}])
def test_wire_rejected_before_balance_or_dispatch(tmp_path, change):
    guard = DispatchGuard(tmp_path, lambda: pytest.fail('preflight'))
    with pytest.raises(RuntimeError):
        guard.check('POST', ENDPOINT + '/chat/completions', {'model': MODEL, 'max_tokens': MAX_OUTPUT, **change})
    assert guard.provider_posts == 0


@pytest.mark.parametrize('balances', [
    (Decimal('0'), Decimal('0')), (PER_SEND / 2, Decimal('0')), (Decimal('1'), Decimal('.01')),
    (Decimal('NaN'), Decimal('0')), (Decimal('1'), Decimal('NaN')),
    (Decimal('-1'), Decimal('0')), (Decimal('1'), Decimal('-.01')),
])
def test_balance_fail_closed(monkeypatch, balances):
    monkeypatch.setattr('local_story_quality_trial._read_balance', lambda key: balances)
    with pytest.raises(RuntimeError):
        balance_preflight('fixture')


def test_preflight_429_is_reported_without_dispatch_retry_or_sensitive_details(tmp_path, monkeypatch):
    from urllib.error import HTTPError

    calls = []
    def deny():
        calls.append(True)
        raise HTTPError('https://fixture.invalid/private-key', 429, 'sensitive-secret', {'Authorization': 'secret'}, None)
    guard_type = DispatchGuard
    monkeypatch.setattr('local_story_quality_trial.DispatchGuard', lambda root, preflight: guard_type(root, deny))
    transport = OfflineTransport()
    root = tmp_path / 'rate-limited'
    report = run_trial(root, transport=transport)
    assert calls == [True] and not transport.requests
    assert report['provider_posts'] == report['committed_turns'] == 0
    assert report['preflight_failure'] == {'type': 'HTTPError', 'http_status': 429}
    assert json.loads((root / 'preflight-failure.json').read_text()) == report['preflight_failure']
    assert 'sensitive-secret' not in json.dumps(report) and 'private-key' not in json.dumps(report)
