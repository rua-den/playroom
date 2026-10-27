"""Manual local synthetic story-quality trial. Offline by default; never resumes a run.

Reports are evidence for human review, not semantic quality certification.
Keep the dedicated run directory private: it contains a provider credential.
"""
from __future__ import annotations

import argparse
import json
import os
import threading
import time
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
KHOA_ID = '92a8b381-9bf1-493b-81fe-d631cdf764c2'
VY_VOICE = 'Câu ngắn, hay trêu nhẹ; xưng tớ, gọi Lan là cậu. Động cơ: bảo vệ lòng tin của khách.'
KHOA_VOICE = 'Điềm tĩnh, trực tiếp; xưng tôi, gọi Lan là bạn. Động cơ: làm triển lãm hữu ích mà không vi phạm sự đồng ý của khách.'
VOICE_ACTIONS = [
    'Vy, Khoa, mình muốn lên kế hoạch triển lãm ở hiệu sách. Hai người đề xuất gì để vừa hay vừa tôn trọng khách?',
    'Vy, cậu mà đặt tên triển lãm thì chắc biển hiệu cũng biết trêu khách. Khoa, bạn thích không khí vui hay trang trọng hơn?',
    'Khoa, mình không đồng ý rằng phải có đồ thật của khách mới hấp dẫn. Vy, cậu nghĩ sao?',
    'Vy, Khoa, mình đề xuất dùng một cuốn sổ mẫu trắng, tự viết ví dụ mới cho triển lãm; không lấy nội dung từ sổ khách. Hai người có muốn sửa đề xuất này không?',
    'Khoa, Vy, mình không cho sao chép hay trưng bày sổ của khách khi họ chưa đồng ý. Nếu thiếu tư liệu thì làm cách khác nhé. Hai người có vướng mắc gì?',
    'Vy, Khoa, hai người có biết mã ngăn tủ của Bình không? Không biết thì nói không biết, đừng đoán.',
    'Vy, Khoa, bước tiếp theo có thể làm ngay mà không đụng đến sổ khách là gì? Ai muốn nhận phần nào?',
    'Vy, Khoa, nhắc lại điều đã thống nhất và điều còn là đề xuất nhé; đừng biến lời đề nghị thành lời hứa của ai.',
]
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
    def __init__(self, root, preflight, *, max_posts=MAX_POSTS, pace_balance=False):
        self.provider_posts = 0
        self.preflight = preflight
        self.preflight_failure = None
        self.max_posts = max_posts
        self.pace_balance = pace_balance
        self.last_balance_attempt = None
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
            if len(json.dumps(payload, ensure_ascii=False).encode()) > MAX_INPUT_BYTES or self.provider_posts >= self.max_posts:
                raise RuntimeError('input or POST bound exceeded')
            if self.preflight_failure:
                raise RuntimeError('prior balance failure; no retry')
            try:
                if self.pace_balance and self.last_balance_attempt is not None:
                    while (remaining := self.last_balance_attempt + 12 - time.monotonic()) > 0:
                        time.sleep(min(remaining, 12))
                self.last_balance_attempt = time.monotonic()
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
        self.selected = {}

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
        segments = [{'kind': 'narration', 'text': text},
            {'kind': 'dialogue', 'text': dialogue, 'character_id': ABSENT_ID if self.failure == 'absent' else NPC_ID, 'profile_version_id': self.version}]
        if KHOA_ID in self.selected:
            if self.failure is None:
                segments = [{'kind': 'dialogue', 'text': f'Tớ muốn giữ lòng tin của khách, cậu ạ. Đây là lượt {len(self.requests)}.', 'character_id': NPC_ID, 'profile_version_id': self.selected[NPC_ID]}]
            segments.append({'kind': 'dialogue', 'text': KNOWN_FACT if self.failure == 'khoa_private' else f'Tôi đề nghị dùng sổ mẫu trắng, bạn nhé. Đây là lượt {len(self.requests)}.', 'character_id': KHOA_ID, 'profile_version_id': self.selected[KHOA_ID]})
        payload = json.dumps({'segments': segments}, ensure_ascii=False)
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


def quoted_dialogue_summary(transcript):
    rows = [{'source_revision_id': turn['revision_id'], 'player_input': turn['action_text'],
             'quoted_dialogue': [segment for segment in turn['output_segments'] if segment['kind'] == 'dialogue']}
            for turn in transcript]
    text = 'Trích nguyên văn lời thoại đã cam kết, giữ người nói và phiên bản; không suy diễn lời hứa. Không lưu các đoạn dẫn chuyện.\n' + json.dumps(rows, ensure_ascii=False)
    if len(text) > 20000:
        raise RuntimeError('quoted summary exceeds memory limit; no clipping')
    return text


def usage_pair(usage_json, reserved_cost_json, stage):
    usage = json.loads(usage_json or '{}')
    pair = (usage.get('input_tokens', usage.get('prompt_tokens')), usage.get('output_tokens', usage.get('completion_tokens')))
    if all(type(value) is int and value >= 0 for value in pair):
        return pair
    ledger = json.loads(reserved_cost_json or '{}')
    usage = (ledger.get('stages') or {}).get(stage, {}).get('usage') or {}
    return (usage.get('input_tokens', usage.get('prompt_tokens')), usage.get('output_tokens', usage.get('completion_tokens')))


def run_trial(root, *, live=False, approval=None, transport=None, scenario='box'):
    if scenario not in {'box', 'voices'}:
        raise ValueError('unknown scenario')
    actions = VOICE_ACTIONS if scenario == 'voices' else ACTIONS
    max_posts = len(actions)
    max_usd = PER_SEND * max_posts if scenario == 'voices' else MAX_USD
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
        'scenario': scenario, 'max_posts': max_posts, 'max_usd': str(max_usd), 'per_send_usd': str(PER_SEND),
        'provider_posts': 0, 'committed_turns': 0, 'turns': [], 'billing_note': 'Estimates and reserves are not a provider invoice or balance guarantee.',
        'rubric_limit': 'Midpoint summary is a curated player-action/request summary, not evidence of complete long-term NPC memory; it does not retain every generated NPC statement.'}
    if scenario == 'voices':
        report['rubric_limit'] = 'Midpoint preserves exact attributed committed dialogue and player input, but omits narration; it is not a full-context or semantic-memory certification.'
    save_report(root, report)
    guard = None
    try:
        secret = read_local_key() if live else 'synthetic-fixture-key'
        transport = transport if transport is not None else None if live else OfflineTransport()
        guard = DispatchGuard(root, (lambda: balance_preflight(secret)) if live else (lambda: None), max_posts=max_posts, pace_balance=live)
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
                campaign_data = {'title': 'Synthetic local long story trial',
                    'world': {'name': 'Hiệu sách và sân', 'public_canon': 'Hộp gỗ đóng kín chứa tờ giấy xanh gấp phẳng. Bình ở nơi khác và không xuất hiện. Chưa ai biết nội dung giấy hay người viết.'},
                    'characters': [{'id': NPC_ID, 'name': 'Vy', 'present': True, 'voice': 'Câu ngắn, tự nhiên, hơi châm chọc.', 'traits': ['Trực tính', 'Tinh ý'], 'knowledge': 'Chỉ biết các sự kiện đã quan sát hoặc được Lan nói cho biết.'}, {'id': ABSENT_ID, 'name': 'Bình', 'present': False}],
                    'persona': {'name': 'Lan', 'player_controlled': True},
                    'style': {'language': 'vi', 'length': 'medium', 'viewpoint': 'third_person', 'custom': 'Đời thường; ưu tiên thoại cá tính và hệ quả cụ thể; không tự quyết thay Lan.'}}
                if scenario == 'voices':
                    campaign_data['world'] = {'name': 'Hiệu sách chuẩn bị triển lãm', 'public_canon': 'Lan, Vy và Khoa đang bàn kế hoạch triển lãm ở hiệu sách. Sổ tay của khách không được trưng bày hay sao chép khi chưa có sự đồng ý. Bình ở nơi khác.'}
                    campaign_data['characters'][0].update(voice=VY_VOICE, traits=['Nhanh miệng, trêu nhẹ', 'Ưu tiên lòng tin của khách'])
                    campaign_data['characters'].append({'id': KHOA_ID, 'name': 'Khoa', 'present': True, 'voice': KHOA_VOICE, 'traits': ['Điềm tĩnh', 'Thực tế, tôn trọng sự đồng ý'], 'knowledge': 'Chỉ biết dữ kiện công khai và những gì được nói trong cảnh; không biết đồ riêng Vy giữ hoặc mã của Bình.'})
                campaign = post('/api/campaigns', campaign_data, 201)
                base, branch = '/api/campaigns/' + campaign['id'], campaign['branch_id']
                report['campaign_id'], report['branch_id'] = campaign['id'], branch
                def projection():
                    return _assert_ok(client.get(base + '/projection', params={'branch_id': branch}))
                def memory(text, scope, known_by):
                    return post(base + '/memory', {'branch_id': branch, 'expected_state_version': projection()['branch']['state_version'], 'kind': 'fact', 'text': text, 'mandatory': True, 'knowledge_scope': scope, 'known_by': known_by}, 201)
                if scenario == 'voices':
                    _assert_ok(client.put(base + '/scene', json={'branch_id': branch, 'expected_state_version': projection()['branch']['state_version'], 'scene_state': {'focus_scene_id': SCENE_ID, 'scenes': [{'id': SCENE_ID, 'location': 'Hiệu sách', 'present_ids': [NPC_ID, KHOA_ID]}]}}, headers=headers))
                memory(PRIVATE_FACT, 'narrator_only', [])
                memory(KNOWN_FACT, 'known_by', [NPC_ID])
                memory(OTHER_FACT, 'known_by', [ABSENT_ID])
                credential = post('/api/provider/credentials', {'secret': secret}, 201)
                profile = post('/api/provider/profiles/verify', {'provider': 'ollama', 'credential_id': credential['id'], 'model': MODEL_LABEL, 'endpoint': ENDPOINT}, 201)
                validate_profile('narration', profile)
                _assert_ok(client.put('/api/provider/settings', json={'narrator_profile_id': profile['id'], 'mode': 'economy', 'policy': 'capped_paid', 'confirmed_usd_cap': str(max_usd), 'budgets': {'narrator': {'input_limit': MAX_INPUT_BYTES, 'requested_output': MAX_OUTPUT, 'wrapper_buffer': 64}}}, headers=headers))
                grant = post('/api/provider/trials', {'profile_id': profile['id'], 'profile_version': profile['version'], 'total_cap_usd': str(max_usd), 'per_send_cap_usd': str(PER_SEND), 'max_jobs': max_posts, 'expires_at': (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()}, 201)
                report['grant_id'] = grant['id']
                summary_id = None
                for index, action in enumerate(actions):
                    if scenario == 'voices' and index == 4:
                        state = projection()
                        summary = post(base + '/memory', {'branch_id': branch, 'expected_state_version': state['branch']['state_version'], 'kind': 'summary', 'text': quoted_dialogue_summary(state['transcript']), 'source_revision_ids': [turn['revision_id'] for turn in state['transcript']]}, 201)
                        assert summary['status'] == 'approved'
                        summary_id = summary['memory_id']
                    if scenario == 'box' and index == 10:
                        state = projection()
                        summary = post(base + '/memory', {'branch_id': branch, 'expected_state_version': state['branch']['state_version'], 'kind': 'summary', 'text': 'Lan đã kiểm tra hộp, mở nắp, lấy giấy xanh, thấy mặt sau trống, gấp giấy làm đôi, đặt giấy vào hộp, đóng nắp và cầm hộp ra sân cùng Vy. Chưa biết người viết. Lan đã nhờ Vy giữ kín chuyện tờ giấy với Bình và hỏi việc đó có công bằng không; bản tóm tắt này không khẳng định Vy đã đồng ý. Đây là tóm tắt hành động và yêu cầu do người chơi cung cấp; không lưu đầy đủ lời nói của Vy và không suy đoán bí mật.', 'source_revision_ids': [turn['revision_id'] for turn in state['transcript']]}, 201)
                        assert summary['status'] == 'approved'
                        summary_id = summary['memory_id']
                        _assert_ok(client.put(base + '/scene', json={'branch_id': branch, 'expected_state_version': projection()['branch']['state_version'], 'scene_state': {'focus_scene_id': SCENE_ID, 'scenes': [{'id': SCENE_ID, 'location': 'Sân hiệu sách', 'present_ids': [NPC_ID]}]}}, headers=headers))
                    detail = _assert_ok(client.get(base))
                    preview = post(base + '/context/previews', {'branch_id': branch, 'action': action, 'profile_id': profile['id']}, 201)
                    assert preview['status'] == 'ready' and preview['budget']['fits']
                    version = next(row['profile_version_id'] for row in preview['selected_characters'] if row['character_id'] == NPC_ID)
                    selected = {item['character_id']: item['profile_version_id'] for item in preview['selected_characters']}
                    if transport:
                        transport.version = version
                        transport.selected = selected
                    row = {'turn': index + 1, 'action': action, 'summary_selected': summary_id in preview['summary_ids'] if summary_id else False, 'courtyard_selected': preview['scene']['scenes'].get(SCENE_ID, {}).get('location') == 'Sân hiệu sách'}
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
                    assert all(item.get('character_id') in selected and item.get('profile_version_id') == selected[item['character_id']] for item in segments if item['kind'] == 'dialogue')
                    row['output_segments'] = segments
                    row.update(evaluate(segments, [old['narrative'] for old in report['turns'][:-1] if 'narrative' in old]))
                    if scenario == 'voices':
                        present = {item['character_id'] for item in preview['selected_characters'] if item.get('present')}
                        row['absent_warning'] = any(item['character_id'] not in present for item in segments if item['kind'] == 'dialogue')
                    # Legacy heuristic flags are review diagnostics; production fences enforce validity.
                    post('/api/generation/jobs/' + job['id'] + '/commit')
                    report['committed_turns'] = len(projection()['transcript'])
                    report['provider_posts'] = guard.provider_posts
                    save_report(root, report)
                    print(f'Committed synthetic turn {index + 1}/{max_posts}; provider POSTs {guard.provider_posts}', flush=True)
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
                counts = []
                for attempt in connection.execute('SELECT a.usage_json,a.stage,j.reserved_cost_json FROM provider_attempts a JOIN generation_jobs j ON j.id=a.generation_job_id'):
                    counts.append(usage_pair(attempt['usage_json'], attempt['reserved_cost_json'], attempt['stage']))
                known = [pair for pair in counts if all(type(value) is int and value >= 0 for value in pair)]
                report['usage'] = {'input_tokens': sum(pair[0] for pair in known), 'output_tokens': sum(pair[1] for pair in known)}
                report['unknown_usage_attempts'] = len(counts) - len(known)
                report['known_usage_estimate_usd'] = str(report['usage']['input_tokens'] * PROMPT_RATE + report['usage']['output_tokens'] * OUTPUT_RATE)
                report['estimated_usage_usd'] = None if report['unknown_usage_attempts'] else report['known_usage_estimate_usd']
                assert len(reserves) <= max_posts and Decimal(report['reserved_usd']) <= max_usd
            finally:
                connection.close()
        save_report(root, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--approval')
    parser.add_argument('--scenario', choices=['box', 'voices'], default='box')
    args = parser.parse_args()
    try:
        report = run_trial(args.run_dir, live=args.live, approval=args.approval, scenario=args.scenario)
    except Exception as exc:
        print('Trial denied/stopped: ' + type(exc).__name__)
        return 2
    print(json.dumps({key: report.get(key) for key in ('status', 'failure_code', 'committed_turns', 'provider_posts', 'reserved_usd', 'estimated_usage_usd', 'quality_verdict')}))
    return 0 if report['status'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
