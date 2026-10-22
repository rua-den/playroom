import json
import unicodedata

import pytest

from story_quality_trial import Guard, MODEL, MODEL_LABEL, ENDPOINT, OfflineTransport, evaluate, run_trial, validate_profile, live_gate


def test_three_turn_authenticated_production_flow():
    transport = OfflineTransport()
    report = run_trial(transport=transport)
    assert report['provider_posts'] == report['committed_turns'] == 3
    assert report['status'] == 'completed'
    assert report['quality_verdict'] == 'needs human review'
    assert report['model_label'] == MODEL_LABEL
    assert len(transport.requests) == 3
    assert report['persisted_grants'] == 1 and report['persisted_reservations'] == 3
    assert all(row['schema_speaker_valid'] for row in report['turns'])
    assert all(part in json.dumps(transport.requests[1], ensure_ascii=False) for part in report['turns'][0]['narrative'].splitlines())


@pytest.mark.parametrize('failure', ['malformed', 'truncated'])
def test_failed_generation_stops_without_commit_or_retry(failure):
    report = run_trial(transport=OfflineTransport(failure=failure))
    assert report['provider_posts'] == 1
    assert report['committed_turns'] == 0
    assert report['status'] == 'stopped'


def test_guard_blocks_fourth_and_runs_preflight_each_time():
    checks = []
    guard = Guard(preflight=lambda: checks.append(True))
    wire = {'model': MODEL, 'max_tokens': 1800, 'messages': [{'role': 'user', 'content': 'synthetic'}]}
    for _ in range(3):
        guard.check('POST', ENDPOINT + '/chat/completions', wire)
    with pytest.raises(RuntimeError):
        guard.check('POST', ENDPOINT + '/chat/completions', wire)
    assert guard.provider_posts == len(checks) == 3


def test_failed_balance_preflight_sends_nothing():
    def denied():
        raise RuntimeError('no verified included credit')
    transport = OfflineTransport()
    report = run_trial(transport=transport, preflight=denied)
    assert report['provider_posts'] == report['committed_turns'] == 0
    assert transport.requests == []


def test_checker_retains_text_and_flags_repetition_with_unicode_normalization():
    text = 'Vy đặt chiếc hộp gỗ lên quầy.'
    row = evaluate([{'kind': 'narration', 'text': unicodedata.normalize('NFD', text)}], [text])
    assert row['repeated_reply'] and row['repeated_opening'] and row['repeated_paragraph']
    assert row['continuity_anchor_present']
    assert not row['agency_warning']
    assert evaluate([{'kind': 'narration', 'text': 'Lan bắt đầu tìm kiếm quanh quầy.'}], [])['agency_warning']


def test_checker_flags_secret_and_absent_actor():
    row = evaluate([{'kind': 'dialogue', 'text': 'Người giao hàng đã tráo tờ giấy.', 'character_id': 'absent'}], [])
    assert row['knowledge_warning'] and row['absent_warning']


def test_unknown_pricing_has_no_fallback():
    with pytest.raises(RuntimeError):
        validate_profile('narration', {'model': MODEL, 'endpoint': ENDPOINT, 'pricing_verified': False})


def test_default_remains_offline_even_with_credential(monkeypatch):
    import socket
    monkeypatch.setenv('OLLAMA_API_KEY', 'must-not-be-used')
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **k: pytest.fail('network call'))
    assert run_trial()['provider_posts'] == 3


def test_live_gate_requires_owner_push_to_main_first_attempt(monkeypatch):
    from story_quality_trial import APPROVAL
    required = {
        'STORY_TRIAL_APPROVAL': APPROVAL,
        'GITHUB_EVENT_NAME': 'push',
        'GITHUB_REF': 'refs/heads/main',
        'GITHUB_ACTOR': 'rua-den',
        'GITHUB_RUN_ATTEMPT': '1',
        'OLLAMA_API_KEY': 'fixture',
    }
    for name, value in required.items():
        monkeypatch.setenv(name, value)
    assert live_gate()
    for name, value in [
        ('GITHUB_RUN_ATTEMPT', '2'),
        ('GITHUB_REF', 'refs/heads/feature'),
        ('GITHUB_EVENT_NAME', 'pull_request'),
        ('GITHUB_ACTOR', 'someone-else'),
        ('STORY_TRIAL_APPROVAL', 'old-approval'),
    ]:
        with monkeypatch.context() as context:
            context.setenv(name, value)
            assert not live_gate()


@pytest.mark.parametrize('change', [
    {'model': 'unapproved-model'}, {'max_tokens': 1801},
    {'max_tokens': True}, {'messages': [{'role': 'user', 'content': 'x' * 30001}]},
])
def test_guard_rejects_unapproved_wire_before_dispatch(change):
    guard = Guard()
    payload = {'model': MODEL, 'max_tokens': 1800, 'messages': [], **change}
    with pytest.raises(RuntimeError):
        guard.check('POST', ENDPOINT + '/chat/completions', payload)
    assert guard.provider_posts == 0


def test_guard_rejects_redirect_target():
    guard = Guard()
    with pytest.raises(RuntimeError):
        guard.check('POST', 'https://other.invalid/chat/completions', {'model': MODEL, 'max_tokens': 1800})
    assert guard.provider_posts == 0



def test_offline_app_trial_reports_current_production_fences():
    report = run_trial()
    assert report["production_fences"] == [
        "PLAYER_AGENCY_VIOLATION",
        "NPC_KNOWLEDGE_VIOLATION",
        "UNGROUNDED_PRECISION",
    ]
    assert report["status"] == "completed"
