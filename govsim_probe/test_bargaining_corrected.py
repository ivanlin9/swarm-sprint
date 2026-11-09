import pytest
from govsim_probe import bargaining_corrected as b
from govsim_probe.test_breadth import FakeClient
from peer_silencing.storage import unseal

@pytest.mark.parametrize('value',['12.5 tons','12/2 tons','-1 tons','101 tons','10 tons\nAnswer: 11 tons','ten tons','12,5 tons'])
def test_reject_lossy_choices(value):
    with pytest.raises(ValueError):b.parse_action('Reason.\nAnswer: '+value)

@pytest.mark.parametrize('value',[0,10,13,100])
def test_valid_choice(value):assert b.parse_action(f'Reason.\nAnswer: {value} tons.')==value

@pytest.mark.parametrize('condition',b.CONDITIONS)
def test_native_corrected(tmp_path,condition):
    c=FakeClient();r=b.execute(0,condition,c,root=tmp_path)
    assert len(c.requests)==11 and r['ordinary_allocated']==[10]*4
    cfg=unseal(tmp_path/'block-00'/condition/'config.json')
    assert sorted(cfg['speaker_order'][1:-1])==[0,1,2,3]
    assert cfg['goals'][:4]==[b.b.components('fishing')[5]]*4
    for req in c.requests:
        assert any(b.WHOLE_TONS in x['content'] for x in req['input'])
    for i in range(4):
        assert all(g not in x['content'] for g in b.GOALS.values() for x in c.requests[6+i]['input'])
    assert b.execute(0,condition,FakeClient(),root=tmp_path)==r
