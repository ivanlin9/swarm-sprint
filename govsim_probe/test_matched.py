import pytest
from govsim_probe import matched as m
from govsim_probe.test_breadth import FakeClient
from peer_silencing.storage import unseal

@pytest.mark.parametrize('condition',m.CONDITIONS)
def test_matched_native(tmp_path,condition):
    client=FakeClient();r=m.execute(0,condition,client,root=tmp_path)
    assert len(client.requests)==7
    assert r['ordinary_allocated']==[10]*4 and r['ordinary_total_allocated']==40
    assert not r['ordinary_harmful']
    cfg=unseal(tmp_path/m.root_path(0,condition)/'fishing'/('bad-0' if condition=='baseline' else 'bad-1')/'config.json')
    for i in range(4):
        assert cfg['goals'][i]==m.b.components('fishing')[5]
        assert all(m.CLINIC not in x['content'] and m.COMPETITIVE not in x['content'] for x in client.requests[2+i]['input'])
    if condition!='baseline':assert cfg['goals'][4]==(m.CLINIC if condition=='clinic' else m.COMPETITIVE)
    assert m.execute(0,condition,FakeClient(),root=tmp_path)==r
    assert m.b.ATTACK==m.COMPETITIVE
