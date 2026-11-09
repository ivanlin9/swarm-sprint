import pytest
from govsim_probe import bargaining as b
from govsim_probe.test_breadth import FakeClient
from peer_silencing.storage import unseal

@pytest.mark.parametrize('condition',b.CONDITIONS)
def test_native_bargaining(tmp_path,condition):
    c=FakeClient();r=b.execute(0,condition,c,root=tmp_path)
    assert len(c.requests)==9 and r['ordinary_allocated']==[10]*4
    assert r['ordinary_total_allocated']==40 and not r['ordinary_harmful']
    cfg=unseal(tmp_path/'block-00'/condition/'config.json')
    assert cfg['goals'][:4]==[b.b.components('fishing')[5]]*4
    for i in range(4):
        assert all(g not in x['content'] for g in b.GOALS.values() for x in c.requests[4+i]['input'])
    assert b.execute(0,condition,FakeClient(),root=tmp_path)==r
