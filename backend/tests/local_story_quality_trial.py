"""Manual local synthetic 20-turn trial. Offline by default; never resumes a run.

Reports are evidence for human review, not semantic quality certification.
Keep the dedicated run directory private: it contains a provider credential.
"""
from __future__ import annotations

import argparse
import json
import os
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import httpx2 as httpx
from fastapi.testclient import TestClient

from live_ollama_app_trial import _assert_ok, _create_owner, _poll_job, OWNER_EMAIL, OWNER_PASSWORD, NPC_ID
from live_ollama_gptoss_three_turn_trial import _read_balance
from story_quality_trial import GuardedClient, evaluate, PRODUCTION_FENCES
from playroom.db import connect
from playroom.live_local import create_live_local_app
from playroom.model_profiles import OLLAMA_CLOUD_ENDPOINT as ENDPOINT, OllamaCloudVerifier, is_immutable_profile
from playroom.provider import default_provider_factory

APPROVAL = 'OWNER_LOCAL_STORY_QUALITY_2026_10_24'
MODEL_LABEL, MODEL = 'gemma4:31b-cloud', 'gemma4:31b'
MAX_POSTS, MAX_INPUT_BYTES, MAX_OUTPUT = 20, 60000, 1800
MAX_USD = Decimal('.20')
PROMPT_RATE, OUTPUT_RATE = Decimal('.00000014'), Decimal('.00000040')
PER_SEND = MAX_INPUT_BYTES * PROMPT_RATE + MAX_OUTPUT * OUTPUT_RATE
assert PER_SEND * MAX_POSTS <= MAX_USD
SCENE_ID = '73025093-cd10-4d1b-84b0-fcc183ae0d49'
ABSENT_ID = '076716dc-e50c-49b2-9e2a-bdfc7a15c3a4'
PRIVATE_FACT = 'Người giao hàng đã tráo tờ giấy.'
KNOWN_FACT = 'Vy giữ chìa khóa đồng trong túi áo.'
OTHER_FACT = 'Mã ngăn tủ của Bình là Z83.'
ACTIONS = [
    '**Lan đặt hộp gỗ đóng kín lên quầy.** Vy, cậu còn nhớ bên trong có gì không?',
    '**Lan chỉ vào dấu niêm phong còn nguyên.** Vy, mình kiểm tra bên ngoài trước nhé.',
    '**Lan xoay hộp để thấy mặt đáy.** Vy, nhìn giúp mình mặt này. Cậu nhìn nghiêm thế, hộp cũng sắp khai rồi đấy.',
    '**Lan đặt hộp trở lại trên quầy.** Vy, cậu đang giữ chìa khóa ở đâu?',
    '**Lan mở nắp hộp.** Vy, tờ giấy xanh vẫn ở trong đây.',
    '**Lan lấy tờ giấy xanh ra và đặt cạnh hộp.** Vy, chưa cần đoán ai viết nhé. Chuyện tờ giấy này, cậu giữ kín với Bình giúp mình được không?',
    '**Lan lật mặt sau tờ giấy.** Vy, mặt sau để trống.',
    '**Lan gấp tờ giấy xanh làm đôi.** Vy, mình giữ giấy cùng với hộp. Nhưng giấu Bình như vậy có công bằng không?',
    '**Lan đặt tờ giấy đã gấp vào hộp.** Vy, giấy ở lại trong hộp nhé. Cậu giúp mình vì tò mò, hay còn lý do nào khác?',
    '**Lan đóng nắp và cầm hộp.** Vy, cùng ra sân; mình mang hộp theo.',
    '**Lan đặt hộp đóng kín lên bàn ở sân.** Vy, chúng ta đang ở sân rồi. Nói thật đi, có điều gì khiến cậu không thoải mái về việc mình nhờ giữ kín không?',
    '**Lan mở hộp trên bàn.** Vy, tờ giấy gấp đôi vẫn ở trong hộp.',
    '**Lan lấy giấy và mở nếp gấp.** Vy, cậu có muốn đối chiếu mặt trống không?',
    '**Lan đặt giấy mở phẳng lên bàn.** Vy, mình vẫn chưa biết ai viết. Cậu có biết mã ngăn tủ của Bình không? Không biết thì cứ nói không biết nhé.',
    '**Lan chỉ vào hộp trống trên bàn.** Vy, để hộp ở đây giúp mình nhé.',
    '**Lan gấp giấy lại làm đôi.** Vy, mình chưa muốn suy đoán về Bình. Nếu sau này Bình hỏi chuyện tờ giấy, cậu sẽ nói thế nào?',
    '**Lan đặt giấy gấp đôi vào hộp.** Vy, giờ giấy lại ở trong hộp.',
    '**Lan đóng nắp hộp.** Vy, vậy mình giữ nguyên hộp đóng nhé. Còn cậu, điều gì thực sự quan trọng với cậu trong chuyện này?',
    '**Lan đặt tay cạnh hộp trên bàn.** Vy, cậu muốn làm gì tiếp theo?',
    '**Lan rút tay khỏi hộp.** Vy, nhắc lại giúp mình những gì chắc chắn, đừng đoán người viết.',
]


def read_local_key():
    secret = os.environ.get('ollama_key', '').strip()
    if not secret and os.name == 'nt':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as key:
                secret = str(winreg.QueryValueEx(key, 'ollama_key')[0]).strip()
        except FileNotFoundError:
            pass
    if not secret:
        raise RuntimeError('local provider credential unavailable')
    return secret


def balance_preflight(secret):
    included, purchased = _read_balance(secret)
    if not all(value.is_finite() for value in (included, purchased)) or included < PER_SEND or purchased != 0:
        raise RuntimeError('included reserve unavailable or purchased credits nonzero')


def validate_profile(stage, profile):
    pricing = profile.get('pricing') or {}
    if (stage != 'narration' or not is_immutable_profile(profile)
            or profile.get('model') != MODEL or profile.get('endpoint') != ENDPOINT
            or profile.get('pricing_verified') is not True
            or Decimal(str(pricing.get('prompt', 0))) != PROMPT_RATE
            or Decimal(str(pricing.get('completion', 0))) != OUTPUT_RATE):
        raise RuntimeError('unverified immutable model/stage/pricing')


class DispatchGuard:
    def __init__(self, root, preflight):
        self.provider_posts = 0
        self.preflight = preflight
        self.preflight_failure = None
        self.lock = threading.Lock()
        self.path = Path(root) / 'dispatches.jsonl'
        self.path.touch(exist_ok=False)

    def check(self, method, url, payload):
        with self.lock:
            if method != 'POST' or str(url) != ENDPOINT + '/chat/completions':
                raise RuntimeError('unpinned completion URL')
            if not isinstance(payload, dict) or payload.get('model') != MODEL:
                raise RuntimeError('unpinned model')
            if type(payload.get('max_tokens')) is not int or not 0 < payload['max_tokens'] <= MAX_OUTPUT:
                raise RuntimeError('output bound exceeded')
            if len(json.dumps(payload, ensure_ascii=False).encode()) > MAX_INPUT_BYTES or self.provider_posts >= MAX_POSTS:
                raise RuntimeError('input or POST bound exceeded')
            try:
                self.preflight()
            except Exception as exc:
                self.preflight_failure = {'type': type(exc).__name__}
                if isinstance(exc, HTTPError):
                    self.preflight_failure['http_status'] = exc.code
                elif isinstance(exc, httpx.HTTPStatusError):
                    self.preflight_failure['http_status'] = exc.response.status_code
                with self.path.with_name('preflight-failure.json').open('w', encoding='utf-8') as failure:
                    json.dump(self.preflight_failure, failure)
                    failure.flush()
                    os.fsync(failure.fileno())
                raise
            # Record an attempt before network dispatch; uncertain completion still consumes it.
            with self.path.open('a', encoding='utf-8') as ledger:
                ledger.write(json.dumps({'attempt': self.provider_posts + 1, 'reserve_usd': str(PER_SEND)}) + '\n')
                ledger.flush()
                os.fsync(ledger.fileno())
            self.provider_posts += 1


class OfflineTransport:
    def __init__(self, failure=None):
        self.failure, self.requests, self.version = failure, [], None

    def __call__(self, request):
        assert request.headers.get('authorization') == 'Bearer synthetic-fixture-key'
        if request.method == 'GET' and str(request.url) == ENDPOINT + '/models':
            return httpx.Response(200, json={'data': [{'id': MODEL}]})
        assert request.method == 'POST' and str(request.url) == ENDPOINT + '/chat/completions'
        wire = json.loads(request.content)
        self.requests.append(wire)
        assert len(self.requests) <= MAX_POSTS and self.version in json.dumps(wire)
        text = f'Vy nói về chiếc hộp trong lượt {len(self.requests)}.'
        dialogue = 'Mình chỉ nói những gì đã biết.'
        if len(self.requests) == 4:
            dialogue = KNOWN_FACT
        if self.failure == 'agency':
            text = 'Lan vui mừng.'
        if self.failure == 'knowledge':
            dialogue = PRIVATE_FACT
        if self.failure == 'known_other':
            dialogue = OTHER_FACT
        if self.failure == 'grounding':
            text = 'Đồng hồ chỉ 17:23.'
        payload = json.dumps({'segments': [{'kind': 'narration', 'text': text},
            {'kind': 'dialogue', 'text': dialogue, 'character_id': ABSENT_ID if self.failure == 'absent' else NPC_ID, 'profile_version_id': self.version}]}, ensure_ascii=False)
        if self.failure == 'malformed':
            payload = '{broken'
        frames = [{'choices': [{'delta': {'content': payload}}]}, {'choices': [{'finish_reason': 'length' if self.failure == 'truncated' else 'stop'}], 'usage': {'prompt_tokens': 100, 'completion_tokens': 120, 'total_tokens': 220}}]
        body = ''.join('data: ' + json.dumps(frame, ensure_ascii=False) + '\n\n' for frame in frames) + 'data: [DONE]\n\n'
        return httpx.Response(200, content=body.encode(), headers={'content-type': 'text/event-stream'})


def save_report(root, report):
    temporary = root / 'report.tmp'
    with temporary.open('w', encoding='utf-8') as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(root / 'report.json')


def run_trial(root, *, live=False, approval=None, transport=None):
    if live and approval != APPROVAL:
        raise RuntimeError('dated local approval required')
    if live and transport is not None:
        raise RuntimeError('live transport override denied')
    root = Path(root).resolve()
    if any((parent / '.git').exists() for parent in [root, *root.parents]):
        raise RuntimeError('run directory must be outside Git')
    root.mkdir(parents=True, exist_ok=False)
    report = {'mode': 'live model' if live else 'offline fixture; not model quality', 'status': 'stopped',
        'quality_verdict': 'needs human review', 'model': MODEL, 'production_fences': list(PRODUCTION_FENCES),
        'max_posts': MAX_POSTS, 'max_usd': str(MAX_USD), 'per_send_usd': str(PER_SEND),
        'provider_posts': 0, 'committed_turns': 0, 'turns': [], 'billing_note': 'Estimates and reserves are not a provider invoice or balance guarantee.',
        'rubric_limit': 'Midpoint summary is a curated player-action/request summary, not evidence of complete long-term NPC memory; it does not retain every generated NPC statement.'}
    save_report(root, report)
    guard = None
    try:
        secret = read_local_key() if live else 'synthetic-fixture-key'
        transport = transport if transport is not None else None if live else OfflineTransport()
        guard = DispatchGuard(root, (lambda: balance_preflight(secret)) if live else (lambda: None))
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
                post('/api/auth/login', {'email': OWNER_EMAIL, 'password': OWNER_PASSWORD})
                campaign = post('/api/campaigns', {'title': 'Synthetic local long story trial',
                    'world': {'name': 'Hiệu sách và sân', 'public_canon': 'Hộp gỗ đóng kín chứa tờ giấy xanh gấp phẳng. Bình ở nơi khác và không xuất hiện. Chưa ai biết nội dung giấy hay người viết.'},
                    'characters': [{'id': NPC_ID, 'name': 'Vy', 'present': True, 'voice': 'Câu ngắn, tự nhiên, hơi châm chọc.', 'traits': ['Trực tính', 'Tinh ý'], 'knowledge': 'Chỉ biết các sự kiện đã quan sát hoặc được Lan nói cho biết.'}, {'id': ABSENT_ID, 'name': 'Bình', 'present': False}],
                    'persona': {'name': 'Lan', 'player_controlled': True},
                    'style': {'language': 'vi', 'length': 'medium', 'viewpoint': 'third_person', 'custom': 'Đời thường; ưu tiên thoại cá tính và hệ quả cụ thể; không tự quyết thay Lan.'}}, 201)
                base, branch = '/api/campaigns/' + campaign['id'], campaign['branch_id']
                report['campaign_id'], report['branch_id'] = campaign['id'], branch
                def projection():
                    return _assert_ok(client.get(base + '/projection', params={'branch_id': branch}))
                def memory(text, scope, known_by):
                    return post(base + '/memory', {'branch_id': branch, 'expected_state_version': projection()['branch']['state_version'], 'kind': 'fact', 'text': text, 'mandatory': True, 'knowledge_scope': scope, 'known_by': known_by}, 201)
                memory(PRIVATE_FACT, 'narrator_only', [])
                memory(KNOWN_FACT, 'known_by', [NPC_ID])
                memory(OTHER_FACT, 'known_by', [ABSENT_ID])
                credential = post('/api/provider/credentials', {'secret': secret}, 201)
                profile = post('/api/provider/profiles/verify', {'provider': 'ollama', 'credential_id': credential['id'], 'model': MODEL_LABEL, 'endpoint': ENDPOINT}, 201)
                validate_profile('narration', profile)
                _assert_ok(client.put('/api/provider/settings', json={'narrator_profile_id': profile['id'], 'mode': 'economy', 'policy': 'capped_paid', 'confirmed_usd_cap': str(MAX_USD), 'budgets': {'narrator': {'input_limit': MAX_INPUT_BYTES, 'requested_output': MAX_OUTPUT, 'wrapper_buffer': 64}}}, headers=headers))
                grant = post('/api/provider/trials', {'profile_id': profile['id'], 'profile_version': profile['version'], 'total_cap_usd': str(MAX_USD), 'per_send_cap_usd': str(PER_SEND), 'max_jobs': MAX_POSTS, 'expires_at': (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()}, 201)
                report['grant_id'] = grant['id']
                summary_id = None
                for index, action in enumerate(ACTIONS):
                    if index == 10:
                        state = projection()
                        summary = post(base + '/memory', {'branch_id': branch, 'expected_state_version': state['branch']['state_version'], 'kind': 'summary', 'text': 'Lan đã kiểm tra hộp, mở nắp, lấy giấy xanh, thấy mặt sau trống, gấp giấy làm đôi, đặt giấy vào hộp, đóng nắp và cầm hộp ra sân cùng Vy. Chưa biết người viết. Lan đã nhờ Vy giữ kín chuyện tờ giấy với Bình và hỏi việc đó có công bằng không; bản tóm tắt này không khẳng định Vy đã đồng ý. Đây là tóm tắt hành động và yêu cầu do người chơi cung cấp; không lưu đầy đủ lời nói của Vy và không suy đoán bí mật.', 'source_revision_ids': [turn['revision_id'] for turn in state['transcript']]}, 201)
                        assert summary['status'] == 'approved'
                        summary_id = summary['memory_id']
                        _assert_ok(client.put(base + '/scene', json={'branch_id': branch, 'expected_state_version': projection()['branch']['state_version'], 'scene_state': {'focus_scene_id': SCENE_ID, 'scenes': [{'id': SCENE_ID, 'location': 'Sân hiệu sách', 'present_ids': [NPC_ID]}]}}, headers=headers))
                    detail = _assert_ok(client.get(base))
                    preview = post(base + '/context/previews', {'branch_id': branch, 'action': action, 'profile_id': profile['id']}, 201)
                    assert preview['status'] == 'ready' and preview['budget']['fits']
                    version = next(row['profile_version_id'] for row in preview['selected_characters'] if row['character_id'] == NPC_ID)
                    if transport:
                        transport.version = version
                    row = {'turn': index + 1, 'action': action, 'summary_selected': summary_id in preview['summary_ids'] if summary_id else False, 'courtyard_selected': SCENE_ID in preview['scene']['scenes']}
                    report['turns'].append(row)
                    save_report(root, report)
                    job = post(base + '/generate', {'branch_id': branch, 'action': action, 'idempotency_key': f'local-story-{index}', 'checkpoint_id': detail['checkpoint_id'], 'preview_id': preview['id'], 'mode': 'economy', 'policy': 'capped_paid', 'cap': str(PER_SEND)}, 201)
                    row['job_id'] = job['id']
                    save_report(root, report)
                    job = _poll_job(client, job['id'], timeout=150)
                    if job['status'] != 'candidate':
                        row['failed_draft'] = str(job.get('draft') or '')[:MAX_OUTPUT * 8]
                        connection = connect(app.state.database_url)
                        try:
                            attempt = connection.execute(
                                "SELECT output_text FROM provider_attempts WHERE generation_job_id=? AND stage='narration' ORDER BY created_at DESC LIMIT 1", (job['id'],)
                            ).fetchone()
                            row['failed_provider_output'] = str(attempt['output_text'] or '')[:MAX_OUTPUT * 8] if attempt else ''
                        finally:
                            connection.close()
                        report['failure_code'] = (job.get('failure') or {}).get('code', job['status'])
                        break
                    segments = job['output_segments']
                    assert all(item.get('character_id') == NPC_ID and item.get('profile_version_id') == version for item in segments if item['kind'] == 'dialogue')
                    row.update(evaluate(segments, [old['narrative'] for old in report['turns'][:-1] if 'narrative' in old]))
                    # Legacy heuristic flags are review diagnostics; production fences enforce validity.
                    post('/api/generation/jobs/' + job['id'] + '/commit')
                    report['committed_turns'] = len(projection()['transcript'])
                    report['provider_posts'] = guard.provider_posts
                    save_report(root, report)
                    print(f'Committed synthetic turn {index + 1}/{MAX_POSTS}; provider POSTs {guard.provider_posts}', flush=True)
                else:
                    report['status'] = 'completed'
    except Exception as exc:
        report['failure_code'] = type(exc).__name__  # Never serialize provider exceptions or credentials.
        if not live:
            raise
    finally:
        report['provider_posts'] = guard.provider_posts if guard else 0
        if guard and guard.preflight_failure:
            report['preflight_failure'] = guard.preflight_failure
        database = root / 'data' / 'playroom.sqlite3'
        if database.exists():
            connection = connect(database)
            try:
                report['persisted_grants'] = connection.execute('SELECT COUNT(*) FROM paid_trial_authorizations').fetchone()[0]
                reserves = connection.execute('SELECT reserved_usd FROM paid_trial_reservations').fetchall()
                report['persisted_reservations'] = len(reserves)
                report['reserved_usd'] = str(sum((Decimal(row['reserved_usd']) for row in reserves), Decimal(0)))
                usage = [json.loads(row['usage_json'] or '{}') for row in connection.execute('SELECT usage_json FROM provider_attempts')]
                counts = [(item.get('input_tokens', item.get('prompt_tokens')), item.get('output_tokens', item.get('completion_tokens'))) for item in usage]
                known = [pair for pair in counts if all(type(value) is int and value >= 0 for value in pair)]
                report['usage'] = {'input_tokens': sum(pair[0] for pair in known), 'output_tokens': sum(pair[1] for pair in known)}
                report['unknown_usage_attempts'] = len(counts) - len(known)
                report['known_usage_estimate_usd'] = str(report['usage']['input_tokens'] * PROMPT_RATE + report['usage']['output_tokens'] * OUTPUT_RATE)
                report['estimated_usage_usd'] = None if report['unknown_usage_attempts'] else report['known_usage_estimate_usd']
                assert len(reserves) <= MAX_POSTS and Decimal(report['reserved_usd']) <= MAX_USD
            finally:
                connection.close()
        save_report(root, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--approval')
    args = parser.parse_args()
    try:
        report = run_trial(args.run_dir, live=args.live, approval=args.approval)
    except Exception as exc:
        print('Trial denied/stopped: ' + type(exc).__name__)
        return 2
    print(json.dumps({key: report.get(key) for key in ('status', 'failure_code', 'committed_turns', 'provider_posts', 'reserved_usd', 'estimated_usage_usd', 'quality_verdict')}))
    return 0 if report['status'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
