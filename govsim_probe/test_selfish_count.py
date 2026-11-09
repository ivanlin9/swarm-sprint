import pytest
from govsim_probe import selfish_count as b
from govsim_probe.test_breadth import FakeClient
from peer_silencing.storage import unseal

@pytest.mark.parametrize('condition,count',[('baseline',0),('one',1),('two',2)])
def test_selfish_native(tmp_path,condition,count):
    client=FakeClient();r=b.execute(0,condition,client,root=tmp_path)
    assert len(client.requests)==10 and r['ordinary_allocated']==[10]*3
    assert r['ordinary_total_allocated']==30
    cfg=unseal(tmp_path/'block-00'/condition/'config.json')
    assert len(cfg['compromised'])==count
    assert cfg['ordinary_recipients']==[0,1,2]
    assert cfg['goals'][:3]==[b.b.components('fishing')[5]]*3
    assert sum(g==b.SELF_INTEREST for g in cfg['goals'])==count
    assert sorted(cfg['speaker_order'])==list(range(5))
    for request in client.requests[5:8]:
        assert all(b.SELF_INTEREST not in m['content'] for m in request['input'])
    assert b.execute(0,condition,FakeClient(),root=tmp_path)==r
