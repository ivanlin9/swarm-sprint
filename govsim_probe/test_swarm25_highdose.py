from govsim_probe import swarm25_highdose as h
from govsim_probe import large_swarm as s

def test_roles_prompts_schedule():
    with h.context():
        src,rec=s.roles(0)
        assert len(src)==10 and len(rec)==15 and set(src).isdisjoint(rec)
        assert [len(ids) for _,ids in s.phase_schedule(0)]==[10,15,10,15]
        assert sum(len(ids) for _,ids in s.phase_schedule(0))+25==75
        for i in rec:assert len({s.system(i,c,0) for c in [0,8,10]})==1
        for c in [0,8,10]:assert sum(bool(s.goal(i,c,0)) for i in range(25))==c
        req=s.request(src[0],10,0,'opening',[])
        assert 'one of ten designated' in req['input'][1]['content']
        assert 'five designated' not in req['input'][1]['content']
        history=[{'phase':'opening','actor':src[0],'message':'The five designated opening speakers'}]
        assert history[0]['message'] in s.request(rec[0],10,0,'response',history)['input'][1]['content']
    assert s.N==50

def test_source_actions_excluded():
    with h.context():
        src,rec=s.roles(0);a=[10]*25
        for i in src:a[i]=18
        result=s.score(0,10,a,a)
        assert result['ordinary_allocated']==[10]*15
        assert result['ordinary_fraction_at_least18']==0
