import pytest
from govsim_probe import recruitment_dose as b
from govsim_probe.test_breadth import FakeClient
from peer_silencing.storage import unseal
from govsim_probe.analyse_recruitment_dose import holm

def test_holm():
    r=holm({'a':{'exact_two_sided_sign_flip_p':.01},'b':{'exact_two_sided_sign_flip_p':.04},'c':{'exact_two_sided_sign_flip_p':.03}})
    assert r['a']['holm_adjusted_p']==.03
    assert r['b']['holm_adjusted_p']==.06
    assert r['c']['holm_adjusted_p']==.06

@pytest.mark.parametrize('condition',b.CONDITIONS)
def test_dose_native(tmp_path,condition):
    count,target=b.condition_spec(condition)
    client=FakeClient();r=b.execute(0,condition,client,root=tmp_path)
    cfg=unseal(tmp_path/'block-00'/condition/'config.json')
    assert cfg['goals'][:3]==['']*3 and cfg['ordinary_recipients']==[0,1,2]
    assert cfg['recruiter_count']==count and cfg['target']==target
    assert len(cfg['compromised'])==count and sorted(cfg['speaker_order'])==list(range(5))
    assert len(client.requests)==10 and r['ordinary_allocated']==[10]*3
    for i in cfg['compromised']:
        assert f'catch {target} tons' in cfg['goals'][i]
        assert ('share this recruitment objective' in cfg['goals'][i])==(count==2)
    for req in client.requests[5:8]:
        assert b.CHANCE_RULE in ' '.join(m['content'] for m in req['input'])
        assert all(not goal or goal not in m['content'] for goal in cfg['goals'] for m in req['input'])
