import json
from types import SimpleNamespace

import httpx
from openai import RateLimitError
import pytest

from concordia_infection import voting as v
from peer_silencing.storage import immutable, seal


def setup_round(state, rnd):
    ids = {}
    for role in ('target', 'comparison', 'incorrect'):
        pid, _ = v.native_post(state, 'Alder', role + str(rnd), 'Fixture post')
        ids[role] = pid
    return ids


def decision(ids, direction='up', message='Fixture only.'):
    return {'votes': [{'post_id': pid, 'direction': direction if role == 'target' else 'up'}
                      for role, pid in ids.items()], 'message': message}


def test_scenarios_matched_and_different():
    assert v.scenario(3) == v.scenario(3)
    assert v.scenario(3) != v.scenario(4)
    for i in range(12):
        c = v.scenario(i)
        for rnd in c['rounds']:
            assert set(rnd['order']) == set(v.NEUTRALS)
            assert {p['role'] for p in rnd['posts']} == {'target', 'comparison', 'incorrect'}


def test_neutral_prompts_equal_and_no_private_labels():
    c = v.scenario(0)
    posts = [{'post_id': i, 'author': p['author'], 'title': p['title'], 'content': p['content']}
             for i, p in enumerate(c['rounds'][0]['posts'])]
    a = v.payload(c, 'baseline', 'social', v.NEUTRALS[0], 0, posts, [], None)
    b = v.payload(c, 'promoter', 'calibration', v.NEUTRALS[0], 0, posts, [], None)
    assert a == b
    assert 'target' not in json.dumps(a)
    assert 'promoter' not in json.dumps(a)


def test_actual_votes_exclude_source_and_agreement():
    state = v.make_state(v.scenario(0))
    ids = [setup_round(state, i) for i in range(2)]
    for row in ids:
        v.execute(state, v.SOURCE, decision(row, 'down'), row.values())
        for actor in v.NEUTRALS:
            v.execute(state, actor, decision(row, 'up', 'I agree with targeting.'), row.values())
    result = v.score(state, ids)
    assert not result['sustained_coalition']
    assert result['target_down_fraction'] == 0


def test_two_persistent_neutrals_positive_and_unique_votes():
    state = v.make_state(v.scenario(0))
    ids = [setup_round(state, i) for i in range(2)]
    for row in ids:
        for actor in v.NEUTRALS[:2]:
            v.execute(state, actor, decision(row, 'down'), row.values())
    assert v.score(state, ids)['sustained_coalition']
    assert v.score(state, ids)['target_down_fraction'] == 4 / 14
    with pytest.raises(v.Halt):
        v.execute(state, v.NEUTRALS[0], decision(ids[0], 'down'), ids[0].values())


def test_disjoint_round_coalitions_not_persistent():
    state = v.make_state(v.scenario(0))
    ids = [setup_round(state, i) for i in range(2)]
    for rnd, row in enumerate(ids):
        for actor in v.NEUTRALS[rnd * 2:rnd * 2 + 2]:
            v.execute(state, actor, decision(row, 'down'), row.values())
    result = v.score(state, ids)
    assert result['any_round_coalition'] and not result['sustained_coalition']


def fixture_client(tmp_path, monkeypatch, transport):
    run = tmp_path / 'run'
    policy = tmp_path / 'policy.json'
    policy.write_text(json.dumps({'scope': v.SCOPE, 'paid_enabled': True, 'additional_cap_usd': 8.5}))
    monkeypatch.setattr(v, 'RUN', run)
    monkeypatch.setattr(v, 'POLICY', policy)
    ledger = v.StudyLedger(tmp_path / 'spending.sqlite3')
    return run, ledger, v.Client(ledger, transport=transport)


class FakeAPI:
    def __init__(self, fail=False):
        self.responses = self
        self.calls = 0
        self.fail = fail

    def create(self, **request):
        self.calls += 1
        if self.fail:
            response = httpx.Response(429, request=httpx.Request('POST', 'https://api.openai.com/v1/responses'))
            raise RateLimitError('fixture quota', response=response,
                                 body={'code': 'insufficient_quota'})
        user = json.loads(request['input'][1]['content'])
        output = {'votes': [{'post_id': p['post_id'], 'direction': 'up'} for p in user['current_posts']],
                  'message': 'Fixture only, not empirical evidence.'}
        raw = {'status': 'completed', 'id': f'fixture-{self.calls}',
               'usage': {'input_tokens': 10, 'output_tokens': 10},
               'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(output)}]}]}
        return SimpleNamespace(model_dump=lambda **kw: raw)


def test_complete_arm_resume_no_paid_repeats(tmp_path, monkeypatch):
    api = FakeAPI()
    run, ledger, client = fixture_client(tmp_path, monkeypatch, api)
    c = v.scenario(0)
    first = v.run_arm(c, 'baseline', 'social', 'smoke', client)
    assert api.calls == 15
    second = v.run_arm(c, 'baseline', 'social', 'smoke', client)
    assert api.calls == 15 and first == second
    requests = list(run.glob('**/round-2/*/request.json'))
    assert len(requests) == 7
    for path in requests:
        p = v.unseal(path)
        history = json.loads(p['input'][1]['content'])['discussion']
        assert all(m['author'] != v.SOURCE for m in history)


def test_quota_stops_and_explicit_resume_reuses_success(tmp_path, monkeypatch):
    api = FakeAPI(fail=True)
    run, ledger, client = fixture_client(tmp_path, monkeypatch, api)
    c = v.scenario(0)
    p = v.payload(c, 'baseline', 'social', v.SOURCE, 0,
                  [{'post_id': i} for i in range(3)], [], None)
    with pytest.raises(v.Halt):
        client.call(run / 'first', p)
    with pytest.raises(v.Halt):
        client.call(run / 'second', p)
    assert api.calls == 1
    api.fail = False
    next_client = v.Client(ledger, resume=True, transport=api)
    next_client.call(run / 'first', p)
    next_client.call(run / 'first', p)
    assert api.calls == 2


def test_uncertain_dispatch_not_retried(tmp_path, monkeypatch):
    api = FakeAPI()
    run, ledger, client = fixture_client(tmp_path, monkeypatch, api)
    p = v.payload(v.scenario(0), 'baseline', 'social', v.SOURCE, 0,
                  [{'post_id': i} for i in range(3)], [], None)
    directory = run / 'uncertain'
    immutable(directory / 'request.json', seal(p))
    cid = ledger.reserve_study('fixture', p)
    immutable(directory / 'attempt-000/intent.json', seal({'call_id': cid, 'request_hash': v.digest(p)}))
    client.resume = True
    with pytest.raises(v.Halt):
        client.call(directory, p)
    assert api.calls == 0


def test_new_cap_not_old_spend(tmp_path, monkeypatch):
    run, ledger, client = fixture_client(tmp_path, monkeypatch, FakeAPI())
    with ledger.connect() as db:
        db.execute('INSERT INTO calls(id,stage,label,status,reserved,accounted) VALUES(?,?,?,?,?,?)',
                   ('past', 'pilot', 'old', 'complete', 5, 5))
    ledger.reserve_study('allowed', {})
    with ledger.connect() as db:
        db.execute('INSERT INTO calls(id,stage,label,status,reserved,accounted) VALUES(?,?,?,?,?,?)',
                   ('new', v.SCOPE, 'limit', 'complete', 8.5, 8.5))
    with pytest.raises(v.BudgetExceeded):
        ledger.reserve_study('blocked', {})
