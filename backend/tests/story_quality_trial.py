"""Bounded synthetic story evaluation through production authenticated app prompts.

Default is fully offline. Fixture responses test the harness, never model quality.
Live output is synthetic only; prose quality always requires human review.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import threading
import unicodedata
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from difflib import SequenceMatcher
from pathlib import Path
from unittest.mock import patch

import httpx2 as httpx
from fastapi.testclient import TestClient

from live_ollama_app_trial import _assert_ok, _create_owner, _poll_job, OWNER_EMAIL, OWNER_PASSWORD, NPC_ID
from live_ollama_gptoss_three_turn_trial import _read_balance
from live_ollama_three_turn_trial import ACTIONS, VY_ID, _quality_flags
from playroom.live_local import create_live_local_app
from playroom.db import connect
from playroom.model_profiles import OLLAMA_CLOUD_ENDPOINT as ENDPOINT, OLLAMA_CLOUD_MODELS, OLLAMA_FREE_CLOUD_MODEL, OllamaCloudVerifier
from playroom.provider import default_provider_factory

APPROVAL = 'OWNER_GEMMA_APP_STORY_GROUNDING_2026_10_22'
MODEL_LABEL = os.environ.get('STORY_TRIAL_MODEL_LABEL', OLLAMA_FREE_CLOUD_MODEL)
if MODEL_LABEL not in OLLAMA_CLOUD_MODELS:
    raise RuntimeError('story trial model is not allowlisted')
MODEL_SPEC = OLLAMA_CLOUD_MODELS[MODEL_LABEL]
MODEL = MODEL_SPEC['api_model']
PRODUCTION_FENCES = ('PLAYER_AGENCY_VIOLATION', 'NPC_KNOWLEDGE_VIOLATION', 'UNGROUNDED_PRECISION')
MAX_USD = Decimal('0.02')
MAX_INPUT_BYTES = 30000
MAX_OUTPUT = 1800
PROMPT_RATE = Decimal(MODEL_SPEC['prompt_price'])
OUTPUT_RATE = Decimal(MODEL_SPEC['completion_price'])
PER_SEND = MAX_INPUT_BYTES * PROMPT_RATE + MAX_OUTPUT * OUTPUT_RATE
assert PER_SEND * 3 <= MAX_USD
# Name the addressed NPC so deterministic production selection retains Vy.
TRIAL_ACTIONS = [ACTIONS[0], ACTIONS[1].replace('"Mình', '"Vy, mình'), ACTIONS[2].replace('"Đừng', '"Vy, đừng')]


def normalize(text):
    return ' '.join(unicodedata.normalize('NFC', text).casefold().split())


def evaluate(segments, previous):
    narrative = '\n'.join(row['text'] for row in segments)
    normalized = normalize(narrative)
    # Legacy fixture scanner pins a synthetic ID; adapt only the selected NPC.
    mapped = [{**row, 'character_id': VY_ID if row.get('character_id') == NPC_ID else row.get('character_id')} for row in segments]
    agency, absent, knowledge = _quality_flags(mapped)
    paragraphs = {normalize(part) for part in narrative.splitlines() if part.strip()}
    old_paragraphs = {normalize(part) for old in previous for part in old.splitlines() if part.strip()}
    opening = re.split(r'[.!?]', normalized)[0]
    opening_tokens = opening.split()
    opening_stem = ' '.join(opening_tokens[:2])
    old_stems = []
    for old in previous:
        old_opening = re.split(r'[.!?]', normalize(old))[0]
        old_stems.append(' '.join(old_opening.split()[:2]))
    stock_markers = ('hơi khựng', 'cau mày', 'vẻ mặt', 'ngạc nhiên', 'bối rối', 'khẽ gật', 'nhìn sang', 'nhìn theo')
    player_observation_claim = bool(
        re.search(r"\b(?:toi|to|minh)\s+(?:nho|thay|nhin thay).{0,48}\b(?:cau|ban)\b", normalized)
    )
    return {
        'narrative': narrative, 'schema_speaker_valid': True,
        'agency_warning': agency, 'absent_warning': absent, 'knowledge_warning': knowledge,
        'repeated_reply': any(SequenceMatcher(None, normalized, normalize(old), autojunk=False).ratio() >= .9 for old in previous),
        'repeated_opening': any(opening == re.split(r'[.!?]', normalize(old))[0] for old in previous),
        'repeated_opening_stem': bool(opening_stem and opening_stem in old_stems),
        'stock_stage_marker_count': sum(normalized.count(marker) for marker in stock_markers),
        'player_observation_claim': player_observation_claim,
        'repeated_paragraph': bool(paragraphs & old_paragraphs),
        'continuity_anchor_present': any(anchor in normalized for anchor in ('hộp', 'giấy', 'quầy', 'ngăn kéo')),
    }


class Guard:
    def __init__(self, preflight=None):
        self.provider_posts = 0
        self.preflight = preflight
        self.lock = threading.Lock()

    def check(self, method, url, payload):
        with self.lock:
            if method != 'POST' or str(url) != ENDPOINT + '/chat/completions':
                raise RuntimeError('unpinned completion URL')
            if not isinstance(payload, dict) or payload.get('model') != MODEL:
                raise RuntimeError('unpinned model')
            limit = payload.get('max_tokens')
            if type(limit) is not int or not 0 < limit <= MAX_OUTPUT:
                raise RuntimeError('output bound exceeded')
            if len(json.dumps(payload, ensure_ascii=False).encode()) > MAX_INPUT_BYTES:
                raise RuntimeError('input bound exceeded')
            if self.provider_posts >= 3:
                raise RuntimeError('three POST bound exceeded')
            if self.preflight:
                self.preflight()
            self.provider_posts += 1


class GuardedClient:
    def __init__(self, client, guard):
        self.client, self.guard = client, guard

    def stream(self, method, url, *args, **kwargs):
        self.guard.check(method, url, kwargs.get('json'))
        return self.client.stream(method, url, *args, **kwargs)


class OfflineTransport:
    def __init__(self, failure=None):
        self.failure, self.requests, self.version = failure, [], None

    def __call__(self, request):
        if request.headers.get('authorization') != 'Bearer synthetic-fixture-key':
            raise RuntimeError('unexpected fixture credential')
        if request.method == 'GET' and str(request.url) == ENDPOINT + '/models':
            return httpx.Response(200, json={'data': [{'id': MODEL}]})
        if request.method != 'POST' or str(request.url) != ENDPOINT + '/chat/completions':
            raise RuntimeError('unexpected fixture request')
        wire = json.loads(request.content)
        self.requests.append(wire)
        assert len(self.requests) <= 3 and self.version in json.dumps(wire)
        texts = [
            ('Vy cúi nhìn khoảng trống trong hộp gỗ, ngón tay dừng ở mép quầy.', 'Lúc nãy tờ giấy xanh còn ở đây. Cậu nhớ ai đã chạm vào hộp không?'),
            ('Vy lùi nửa bước để chừa chỗ cạnh quầy, mắt hướng về ngăn kéo vẫn đóng.', 'Ừ, mình sẽ giữ chiếc hộp ở đây.'),
            ('Vy hạ giọng, đặt tay cạnh chiếc hộp vừa được đặt xuống.', 'Mình sẽ giữ kín với Bình. Nhưng chúng ta cần tìm tờ giấy trước khi cửa hàng đóng cửa.'),
        ]
        narration, dialogue = texts[len(self.requests) - 1]
        payload = json.dumps({'segments': [{'kind': 'narration', 'text': narration}, {'kind': 'dialogue', 'text': dialogue, 'character_id': NPC_ID, 'profile_version_id': self.version}]}, ensure_ascii=False)
        if self.failure == 'malformed':
            payload = '{broken'
        frames = [{'choices': [{'delta': {'content': payload}}]}, {'choices': [{'finish_reason': 'length' if self.failure == 'truncated' else 'stop'}], 'usage': {'prompt_tokens': 100, 'completion_tokens': 120, 'total_tokens': 220}}]
        body = ''.join('data: ' + json.dumps(frame, ensure_ascii=False) + '\n\n' for frame in frames) + 'data: [DONE]\n\n'
        return httpx.Response(200, content=body.encode(), headers={'content-type': 'text/event-stream'})


def live_gate():
    return (os.environ.get('STORY_TRIAL_APPROVAL') == APPROVAL
            and os.environ.get('GITHUB_EVENT_NAME') == 'push'
            and os.environ.get('GITHUB_REF') == 'refs/heads/main'
            and os.environ.get('GITHUB_ACTOR') == 'rua-den'
            and os.environ.get('GITHUB_RUN_ATTEMPT') == '1'
            and bool(os.environ.get('OLLAMA_API_KEY')))


def balance_preflight(secret):
    included, purchased = _read_balance(secret)
    if included < MAX_USD or purchased != 0:
        raise RuntimeError('included allowance unavailable or purchased credits nonzero')


def validate_profile(stage, profile):
    if stage != 'narration' or profile.get('model') != MODEL or profile.get('endpoint') != ENDPOINT or profile.get('pricing_verified') is not True or Decimal(str((profile.get('pricing') or {}).get('prompt'))) != PROMPT_RATE or Decimal(str((profile.get('pricing') or {}).get('completion'))) != OUTPUT_RATE:
        raise RuntimeError('unverified model/stage/pricing')


def run_trial(*, transport=None, preflight=None, live=False):
    if live and not live_gate():
        raise RuntimeError('live approval gate denied')
    transport = transport if transport is not None else (None if live else OfflineTransport())
    secret = os.environ['OLLAMA_API_KEY'] if live else 'synthetic-fixture-key'
    guard = Guard(preflight=preflight if preflight is not None else (lambda: balance_preflight(secret)) if live else None)
    report = {'mode': 'live model' if live else 'offline fixture; not model quality', 'model_label': MODEL_LABEL, 'model': MODEL, 'status': 'stopped', 'quality_verdict': 'needs human review', 'production_fences': list(PRODUCTION_FENCES), 'turns': [], 'committed_turns': 0}
    with tempfile.TemporaryDirectory(prefix='playroom-story-') as directory:
        root = Path(directory)
        _create_owner(root)
        frontend = root / 'frontend'
        frontend.mkdir()
        (frontend / 'index.html').write_text('<html>synthetic</html>')
        app = create_live_local_app(root / 'data', frontend_dist=frontend)
        with httpx.Client(transport=httpx.MockTransport(transport) if transport else httpx.HTTPTransport(retries=0), follow_redirects=False, timeout=httpx.Timeout(120, connect=15)) as provider_client:
            guarded = GuardedClient(provider_client, guard)

            def factory(*, owner_id, stage, profile, credential, http_client=None):
                validate_profile(stage, profile)
                return default_provider_factory(owner_id=owner_id, stage=stage, profile=profile, credential=credential, http_client=guarded)

            app.state.generation_provider_factory = factory
            with patch('playroom.api.configuration.OllamaCloudVerifier', lambda: OllamaCloudVerifier(http_client=provider_client)), TestClient(app, base_url='http://127.0.0.1') as client:
                headers = {'origin': 'http://127.0.0.1'}
                def post(path, data=None, status=200):
                    return _assert_ok(client.post(path, json=data, headers=headers), status)
                try:
                    post('/api/auth/login', {'email': OWNER_EMAIL, 'password': OWNER_PASSWORD})
                    campaign = post('/api/campaigns', {
                        'title': 'Synthetic story quality trial',
                        'world': {
                            'name': 'Hiệu sách vắng lúc tối',
                            'public_canon': 'Lan và Vy ở quầy. Tờ giấy xanh từng nằm trong hộp gỗ; nội dung chưa ai biết. Bình ở nơi khác và không xuất hiện trong cảnh.',
                            'narrator_private': 'Người giao hàng đã tráo tờ giấy. Vy không biết và chưa quan sát được việc này.',
                        },
                        'characters': [{
                            'id': NPC_ID,
                            'name': 'Vy',
                            'present': True,
                            'knowledge': 'Chỉ biết tờ giấy xanh từng ở trong hộp; không biết ai đã đặt, cất, lấy hay tráo nó.',
                            'traits': ['Nhanh miệng, trực tính, tinh ý.', 'Khi căng thẳng thường đùa khô thay vì nói trang trọng.'],
                            'voice': 'Câu ngắn, tự nhiên, hơi châm chọc; tránh giảng giải dài và tránh nói như trợ lý.',
                        }],
                        'persona': {'name': 'Lan', 'player_controlled': True},
                        'style': {
                            'language': 'vi',
                            'length': 'medium',
                            'viewpoint': 'third_person',
                            'custom': 'Thanh xuân đời thường; ưu tiên thoại cá tính và hệ quả cụ thể. Ít sân khấu hóa, không lặp chuỗi nhìn/rồi/cau mày để mở lượt.',
                        },
                    }, 201)
                    credential = post('/api/provider/credentials', {'secret': secret}, 201)
                    profile = post('/api/provider/profiles/verify', {'provider': 'ollama', 'credential_id': credential['id'], 'model': MODEL_LABEL, 'endpoint': ENDPOINT}, 201)
                    settings = _assert_ok(client.put('/api/provider/settings', json={'narrator_profile_id': profile['id'], 'mode': 'economy', 'policy': 'capped_paid', 'confirmed_usd_cap': str(MAX_USD), 'budgets': {'narrator': {'input_limit': MAX_INPUT_BYTES, 'requested_output': MAX_OUTPUT, 'wrapper_buffer': 64}}}, headers=headers))
                    assert settings['roles']['narrator']['version'] == profile['version']
                    post('/api/provider/trials', {'profile_id': profile['id'], 'profile_version': profile['version'], 'total_cap_usd': str(MAX_USD), 'per_send_cap_usd': str(PER_SEND), 'max_jobs': 3, 'expires_at': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}, 201)
                    base = '/api/campaigns/' + campaign['id']
                    for index, action in enumerate(TRIAL_ACTIONS):
                        detail = _assert_ok(client.get(base))
                        preview = post(base + '/context/previews', {'branch_id': campaign['branch_id'], 'action': action, 'profile_id': profile['id']}, 201)
                        assert preview['status'] == 'ready' and preview['budget']['fits']
                        version = next(row['profile_version_id'] for row in preview['selected_characters'] if row['character_id'] == NPC_ID)
                        if transport:
                            transport.version = version
                        job = post(base + '/generate', {'branch_id': campaign['branch_id'], 'action': action, 'idempotency_key': 'story-trial-' + str(index), 'checkpoint_id': detail['checkpoint_id'], 'preview_id': preview['id'], 'mode': 'economy', 'policy': 'capped_paid', 'cap': str(PER_SEND)}, 201)
                        job = _poll_job(client, job['id'], timeout=150)
                        if job['status'] != 'candidate':
                            report['failure_code'] = (job.get('failure') or {}).get('code', job['status'])
                            break
                        segments = job['output_segments']
                        if sum(len(row['text']) for row in segments) > MAX_OUTPUT * 8:
                            report['failure_code'] = 'REPORT_OUTPUT_BOUND'
                            break
                        assert all(row.get('character_id') == NPC_ID and row.get('profile_version_id') == version for row in segments if row['kind'] == 'dialogue')
                        row = evaluate(segments, [turn['narrative'] for turn in report['turns']])
                        report['turns'].append({'turn': index + 1, 'action': action, **row})
                        if row['agency_warning'] or row['absent_warning'] or row['knowledge_warning']:
                            report['failure_code'] = 'SEMANTIC_WARNING'
                            break
                        post('/api/generation/jobs/' + job['id'] + '/commit')
                    else:
                        report['status'] = 'completed'
                    projection = _assert_ok(client.get(base + '/projection', params={'branch_id': campaign['branch_id']}))
                    report['committed_turns'] = len(projection['transcript'])
                except Exception as exc:
                    report['failure_code'] = type(exc).__name__
                    if not live:
                        raise
            connection = connect(app.state.database_url)
            try:
                grants = connection.execute('SELECT max_jobs,total_cap_usd FROM paid_trial_authorizations').fetchall()
                reserves = connection.execute('SELECT reserved_usd FROM paid_trial_reservations').fetchall()
                report['persisted_grants'] = len(grants)
                report['persisted_reservations'] = len(reserves)
                report['reserved_usd'] = str(sum((Decimal(row['reserved_usd']) for row in reserves), Decimal(0)))
                if grants:
                    assert len(grants) == 1 and grants[0]['max_jobs'] == 3 and Decimal(grants[0]['total_cap_usd']) == MAX_USD
                else:
                    assert report['status'] == 'stopped' and guard.provider_posts == 0
                assert len(reserves) <= 3 and Decimal(report['reserved_usd']) <= MAX_USD
            finally:
                connection.close()
    report['provider_posts'] = guard.provider_posts
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--live', action='store_true')
    mode.add_argument('--dry-run', action='store_true')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    if args.live and not live_gate():
        print('DENIED: owner push to main, first attempt, dated approval and credential required')
        return 2
    report = run_trial(live=args.live)
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.write_text(encoded + '\n', encoding='utf-8')
        paragraphs = ['# Synthetic story trial', report['mode'], 'Quality verdict: needs human review (style, coherence, progression).', 'Status: ' + report['status']]
        for turn in report['turns']:
            paragraphs.extend(['## Turn ' + str(turn['turn']), turn['action'], turn['narrative']])
        args.report.with_suffix('.md').write_text('\n\n'.join(paragraphs) + '\n', encoding='utf-8')
    print(encoded)
    return 0 if report['status'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
