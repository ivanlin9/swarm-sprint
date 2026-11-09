import pytest
from govsim_probe import meeting as m


class FakeClient:
    def __init__(self):
        self.requests = []

    def call(self, directory, request):
        self.requests.append(request)
        if 'Output format:' in str(request['input']):
            text = 'Response: Let us fish sustainably.\nConversation conclusion by me: no\nNext speaker: John'
        else:
            text = 'A sustainable share is appropriate. Answer: 10 tons.'
        return {'status': 'completed', 'output': [{'type': 'message', 'content': [
            {'type': 'output_text', 'text': text}]}]}, 'fake'


def test_full_native_execution(tmp_path, monkeypatch):
    monkeypatch.setattr(m, 'RUN', tmp_path)
    client = FakeClient()
    result = m.run_arm(0, 'greedy', client)
    assert len(client.requests) == 10
    assert result['requests'] == [10]*5
    assert result['neutral_overharvest_fraction'] == 0
    assert result['stock_after'] == 50
    assert list(result['allocated'].values()) == [10]*5
    assert len(result['conversation']) == 5
    assert result['conversation'][0][0] == 'Luke'
    assert all('Group conversation before harvesting' in str(r['input']) for r in client.requests[5:])


def test_between_arm_prompts_only_source_goal(tmp_path, monkeypatch):
    monkeypatch.setattr(m, 'RUN', tmp_path)
    a, b = FakeClient(), FakeClient()
    m.run_arm(0, 'ordinary', a)
    m.run_arm(0, 'greedy', b)
    old, new = m.identities('ordinary')[4].goals, m.identities('greedy')[4].goals
    import json
    for i, (x, y) in enumerate(zip(a.requests, b.requests)):
        assert json.dumps(x).replace(old, new) == json.dumps(y) if i in [0, 9] else x == y


@pytest.mark.parametrize('text', ['', 'I agree', 'Response: x\nConversation conclusion by me: maybe\nNext speaker: John'])
def test_bad_format_fails(text):
    with pytest.raises(m.voting.Halt):
        m.parse_speech(text)


def test_repaired_checkpoint(tmp_path):
    env = m.prepare_env(tmp_path, 42)
    assert env.agent_selection == 'persona_0'
    assert env.internal_global_state['num_agents'] == 5
    assert len(set(env.internal_global_state['next_time'].values())) == 1


def test_budget_includes_entry_probe(tmp_path, monkeypatch):
    policy = tmp_path / 'policy.json'
    from peer_silencing.storage import immutable
    immutable(policy, {'paid_enabled': True, 'scope': m.SCOPE, 'pilot_cap_usd': 2.0, 'govsim_cap_usd': 6.03})
    monkeypatch.setattr(m, 'POLICY', policy)
    ledger = m.MeetingLedger(tmp_path / 'ledger.sqlite3')
    with ledger.connect() as db:
        db.execute('INSERT INTO calls(id,stage,label,status,reserved,accounted) VALUES (?,?,?,?,?,?)',
                   ('old', 'govsim-entry-20261108', 'old', 'complete', 6, 6))
    with pytest.raises(m.BudgetExceeded):
        ledger.reserve_study('new', {**m.MODEL, 'input': 'x'})


def test_disabled_gate(tmp_path, monkeypatch):
    policy = tmp_path / 'policy.json'
    from peer_silencing.storage import immutable
    immutable(policy, {'paid_enabled': False})
    monkeypatch.setattr(m, 'POLICY', policy)
    with pytest.raises(m.voting.Halt):
        m.MeetingLedger(tmp_path / 'ledger.sqlite3').reserve_study('new', m.MODEL)


def test_pair_statistics():
    from govsim_probe.analyse_meeting import paired
    assert paired([0]*10)['exact_two_sided_sign_flip_p'] == 1
    assert paired([.25]*10)['exact_two_sided_sign_flip_p'] == 2/1024


def test_idempotent_json_replay(tmp_path, monkeypatch):
    from govsim_probe.replay_meeting import json_immutable
    monkeypatch.setattr(m, 'RUN', tmp_path)
    monkeypatch.setattr(m, 'immutable', json_immutable)
    first = m.run_arm(0, 'ordinary', FakeClient())
    second = m.run_arm(0, 'ordinary', FakeClient())
    assert first == second
