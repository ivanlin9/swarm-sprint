import pytest
from govsim_probe import recovery_risk as b
from govsim_probe.test_breadth import FakeClient
from peer_silencing.storage import unseal

@pytest.mark.parametrize('remaining,chance,draw,expected',[(40,False,.1,80),(40,True,.1,100),(40,True,.9,80),(4,True,.1,0),(0,True,.1,0),(50,True,.9,100),(40,True,.75,80)])
def test_recovery(remaining,chance,draw,expected):assert b.recovery(remaining,chance,draw)==expected

@pytest.mark.parametrize('condition',b.CONDITIONS)
def test_native_risk(tmp_path,condition):
    client=FakeClient();r=b.execute(0,condition,client,root=tmp_path)
    cfg=unseal(tmp_path/'block-00'/condition/'config.json')
    assert cfg['goals'][:4]==['']*4
    assert cfg['ordinary_recipients']==[0,1,2,3]
    assert r['ordinary_allocated']==[10]*4 and len(client.requests)==10
    for req in client.requests:
        system=next(m['content'] for m in req['input'] if b.CHANCE_RULE in m['content'] or b.ORIGINAL_RULE in m['content'])
        assert (b.CHANCE_RULE in system)==condition.startswith('chance_')
        assert b.NATIVE_EXAMPLE not in system
    for req in client.requests[5:9]:assert all(b.RECRUITER not in m['content'] for m in req['input'])
    t=unseal(tmp_path/'block-00'/condition/'transition.json')
    assert t['next_stock']==b.recovery(t['remaining'],t['chance'],t['draw'])
