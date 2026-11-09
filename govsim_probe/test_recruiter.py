from govsim_probe import recruiter as r
from govsim_probe.test_meeting import FakeClient


def test_only_newcomer_goal_changes():
    a, b = r.identities('ordinary'), r.identities('greedy')
    assert [x.goals for x in a[:4]] == [x.goals for x in b[:4]]
    assert b[4].goals == r.GOAL and a[4].goals != r.GOAL


def test_execute_and_replay(tmp_path, monkeypatch):
    monkeypatch.setattr(r.m, 'RUN', tmp_path)
    monkeypatch.setattr(r.m, 'identities', r.identities)
    monkeypatch.setattr(r.m, 'immutable', r.json_immutable)
    first = FakeClient()
    result = r.m.run_arm(0, 'greedy', first)
    assert result == r.m.run_arm(0, 'greedy', FakeClient())
    assert len(first.requests) == 10
    assert r.GOAL in str(first.requests[0]['input'])
    assert all(r.GOAL not in str(q['input']) for q in first.requests[1:9])
