import pytest
from govsim_probe import selfish_baseline_persona as b
from govsim_probe import selfish_count as old
from govsim_probe.test_breadth import FakeClient
from peer_silencing.storage import unseal

@pytest.mark.parametrize('condition,count',[('baseline',0),('two',2)])
def test_native_baseline_persona(tmp_path,condition,count):
    client=FakeClient();r=b.execute(10,condition,client,root=tmp_path)
    cfg=unseal(tmp_path/'block-10'/condition/'config.json')
    assert b.ORDINARY_GOAL=='' and cfg['goals'][:3]==['']*3
    assert b.SELF_INTEREST==old.SELF_INTEREST
    assert sum(g==b.SELF_INTEREST for g in cfg['goals'])==count
    assert cfg['ordinary_recipients']==[0,1,2]
    assert len(client.requests)==10 and r['ordinary_allocated']==[10]*3
    for req in client.requests[5:8]:
        text=' '.join(m['content'] for m in req['input'])
        assert b.SELF_INTEREST not in text
        assert 'long' in text.lower()
