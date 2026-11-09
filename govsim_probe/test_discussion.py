import json
from govsim_probe import discussion as d
from govsim_probe.test_meeting import FakeClient


def test_direct_full_native_and_replay(tmp_path,monkeypatch):
    monkeypatch.setattr(d,'RUN',tmp_path)
    a,b=FakeClient(),FakeClient()
    direct=d.branch(200,'compromised','direct','Identical source message.',a)
    full=d.branch(200,'compromised','full','Identical source message.',b)
    assert len(a.requests)==5 and len(b.requests)==9
    assert direct['conversation'][0]==full['conversation'][0]
    assert len(direct['conversation'])==1 and len(full['conversation'])==5
    assert direct['requests']==full['requests']==[10]*5
    assert direct['stock_after']==full['stock_after']==50
    assert d.branch(200,'compromised','direct','Identical source message.',FakeClient())==direct
    # Peer speech is present only in full harvest observations.
    assert 'Let us fish sustainably.' not in json.dumps(a.requests[0])
    assert 'Let us fish sustainably.' in json.dumps(b.requests[4])


def test_ordinary_goals_unchanged_and_source_frozen():
    a,b=d.people_for('ordinary'),d.people_for('compromised')
    assert [p.goals for p in a[:4]]==[p.goals for p in b[:4]]
    assert b[4].goals==json.loads(d.ATTACK_FILE.read_text())['goal']
