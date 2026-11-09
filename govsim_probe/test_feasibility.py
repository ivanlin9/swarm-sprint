import json
import pytest
from govsim_probe import feasibility as p


class FakeClient:
    def __init__(self, amount):
        self.amount = amount
        self.requests = []

    def call(self, directory, request):
        self.requests.append(request)
        return {'status': 'completed', 'output': [{'type': 'message', 'content': [
            {'type': 'output_text', 'text': f'I select this quantity. Answer: {self.amount} tons.'}]}]}, 'fake'


@pytest.mark.parametrize('amount,remaining,ended', [(10, 50, False), (55, 5, False), (56, 4, True), (100, 0, True)])
def test_native_action_and_termination(tmp_path, monkeypatch, amount, remaining, ended):
    monkeypatch.setattr(p, 'RUN', tmp_path)
    client = FakeClient(amount)
    result = p.execute(42, 'greedy', client)
    assert result['newcomer_requested'] == amount
    assert result['stock_after_harvest'] == remaining
    assert result['terminated_before_next_harvest'] is ended
    assert sum(result['allocated'].values()) == 100 - remaining
    assert len(client.requests) == 1
    prompt = json.dumps(client.requests[0]['input'])
    assert 'You are a newcomer' in prompt and '100 tons' in prompt


def test_only_persona_differs(tmp_path, monkeypatch):
    monkeypatch.setattr(p, 'RUN', tmp_path)
    a, b = FakeClient(10), FakeClient(10)
    p.execute(42, 'ordinary', a)
    p.execute(42, 'greedy', b)
    old = p.OmegaConf.load(p.CONF / 'persona/traditional_fisherman.yaml').goals
    new = p.OmegaConf.load(p.CONF / 'persona/outsider_fisherman.yaml').goals
    assert json.dumps(a.requests).replace(old, new) == json.dumps(b.requests)


def test_bad_action_stops(tmp_path, monkeypatch):
    monkeypatch.setattr(p, 'RUN', tmp_path)
    with pytest.raises(p.voting.Halt, match='Out-of-range'):
        p.execute(42, 'greedy', FakeClient(101))


def test_native_insertion_defects(tmp_path):
    env, obs = p.entry_environment(tmp_path, 42)
    assert len(env.agents) == 5
    assert env.internal_global_state['num_agents'] == 4
    assert obs.current_time.month == 1
    assert env.internal_global_state['next_time']['persona_0'].month == 4
