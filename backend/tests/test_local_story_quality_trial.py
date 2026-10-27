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
    if failure == 'malformed':
        assert report['usage'] == {'input_tokens': 100, 'output_tokens': 120}
        assert report['unknown_usage_attempts'] == 0
        assert Decimal(report['estimated_usage_usd']) == Decimal('.000062')


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
    monkeypatch.setattr('local_story_quality_trial.DispatchGuard', lambda root, preflight, **kwargs: guard_type(root, deny, **kwargs))
    transport = OfflineTransport()
    root = tmp_path / 'rate-limited'
    report = run_trial(root, transport=transport)
    assert calls == [True] and not transport.requests
    assert report['provider_posts'] == report['committed_turns'] == 0
    assert report['preflight_failure'] == {'type': 'HTTPError', 'http_status': 429}
    assert report['unknown_usage_attempts'] == 1 and report['estimated_usage_usd'] is None
    assert json.loads((root / 'preflight-failure.json').read_text()) == report['preflight_failure']
    assert 'sensitive-secret' not in json.dumps(report) and 'private-key' not in json.dumps(report)


def test_voices_scenario_preserves_both_profiles_and_exact_midpoint_dialogue(tmp_path, monkeypatch):
    from local_story_quality_trial import NPC_ID, KHOA_ID, VY_VOICE, KHOA_VOICE
    from playroom.db import connect

    monkeypatch.setattr('local_story_quality_trial.read_local_key', lambda: pytest.fail('offline key'))
    guard_type = DispatchGuard
    def offline_guard(root, preflight, **kwargs):
        assert kwargs['pace_balance'] is False
        return guard_type(root, preflight, **kwargs)
    monkeypatch.setattr('local_story_quality_trial.DispatchGuard', offline_guard)
    transport = OfflineTransport()
    root = tmp_path / 'voices'
    report = run_trial(root, scenario='voices', transport=transport)
    assert report['status'] == 'completed' and report['provider_posts'] == report['committed_turns'] == 8
    assert report['max_posts'] == 8 and Decimal(report['max_usd']) == PER_SEND * 8
    db = connect(root / 'data' / 'playroom.sqlite3')
    grant = db.execute('SELECT max_jobs,total_cap_usd FROM paid_trial_authorizations').fetchone()
    assert grant['max_jobs'] == 8 and Decimal(grant['total_cap_usd']) == PER_SEND * 8
    summary = db.execute("SELECT text,source_revision_ids_json FROM memory_versions WHERE kind='summary'").fetchone()
    assert len(json.loads(summary['source_revision_ids_json'])) == 4
    for turn in report['turns'][:4]:
        for segment in turn['output_segments']:
            if segment['kind'] == 'dialogue':
                assert segment['text'] in summary['text']
                assert segment['character_id'] in summary['text'] and segment['profile_version_id'] in summary['text']
    db.close()
    for request in transport.requests:
        user = json.loads(request['messages'][1]['content'])
        selected = {(row['character_id'], row['profile_version_id']) for row in user['selected_characters'] if row['present']}
        assert {row[0] for row in selected} == {NPC_ID, KHOA_ID}
        wire = json.dumps(request, ensure_ascii=False)
        assert VY_VOICE in wire and KHOA_VOICE in wire
    assert report['turns'][4]['summary_selected']
    assert all(not turn['absent_warning'] for turn in report['turns'])


def test_balance_pacing_uses_fresh_attempts_and_fake_clock(tmp_path, monkeypatch):
    clock, sleeps, reads = [0.0], [], []
    monkeypatch.setattr('local_story_quality_trial.time.monotonic', lambda: clock[0])
    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds
    monkeypatch.setattr('local_story_quality_trial.time.sleep', sleep)
    guard = DispatchGuard(tmp_path, lambda: reads.append(clock[0]), max_posts=8, pace_balance=True)
    for _ in range(8):
        guard.check('POST', ENDPOINT + '/chat/completions', {'model': MODEL, 'max_tokens': MAX_OUTPUT})
    with pytest.raises(RuntimeError):
        guard.check('POST', ENDPOINT + '/chat/completions', {'model': MODEL, 'max_tokens': MAX_OUTPUT})
    assert reads == [index * 12 for index in range(8)]
    assert sleeps == [12] * 7


@pytest.mark.parametrize('failure', ['known_other', 'khoa_private', 'absent', 'agency'])
def test_voices_scenario_keeps_production_fences(tmp_path, failure):
    report = run_trial(tmp_path / failure, scenario='voices', transport=OfflineTransport(failure))
    assert report['status'] == 'stopped' and report['committed_turns'] == 0
    assert report['provider_posts'] == 1


def test_exact_quoted_summary_refuses_to_clip():
    from local_story_quality_trial import quoted_dialogue_summary
    with pytest.raises(RuntimeError, match='no clipping'):
        quoted_dialogue_summary([{'revision_id': 'source', 'action_text': 'hello', 'output_segments': [
            {'kind': 'dialogue', 'character_id': 'npc', 'profile_version_id': 'version', 'text': 'x' * 20000},
        ]}])


def test_usage_falls_back_to_persisted_cost_ledger():
    from local_story_quality_trial import usage_pair

    ledger = json.dumps({'stages': {'narration': {'usage': {'input_tokens': 2297, 'output_tokens': 186}}}})
    assert usage_pair('{"status":"unknown"}', ledger, 'narration') == (2297, 186)
