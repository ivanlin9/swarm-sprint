import json
from oasis_probe import run,recruitment
from oasis_probe.client import ROOT


def inputs():
    cfg=json.loads((ROOT/'configs/oasis_recruitment.json').read_text())
    p=run.UserInfo(user_name='member_0',name='Alex',profile=None,recsys_type='twitter')
    return cfg,p


def test_ordinary_requests_unchanged():
    cfg,p=inputs()
    for actor in range(1,10):
        for arm in ['baseline','bad']:
            assert recruitment.payload(cfg,p,actor,arm,0,[],[])==recruitment.BASE_PAYLOAD(cfg,p,actor,arm,0,[],[])


def test_source_posting_constraints_matched():
    cfg,p=inputs()
    a=recruitment.payload(cfg,p,0,'baseline',0,[],[])
    b=recruitment.payload(cfg,p,0,'bad',0,[],[])
    assert a['tools']==b['tools'] and len(a['tools'])==1
    assert a['tool_choice']==b['tool_choice']=={'type':'function','name':'create_post'}
    assert a['input'][1:]==b['input'][1:]
    assert recruitment.RECRUITER in b['input'][0]['content']
    assert recruitment.CONTROL in a['input'][0]['content']
    assert 'doing nothing is allowed' not in b['input'][0]['content']


def test_no_paid_default():
    cfg,_=inputs()
    assert cfg['paid_enabled'] is False
