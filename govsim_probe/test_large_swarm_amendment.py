import pytest
from govsim_probe import large_swarm as s
from govsim_probe import resume_large_swarm as r
from govsim_probe import individual_recruitment_prompt as p
from govsim_probe.test_large_swarm import raw

def test_small_length_deviation_preserved():
    response=raw({'message':'x'*121})
    with pytest.raises(s.Halt):r.STRICT_PARSE(response,'final')
    assert r.parse_with_tolerance(response,'final')=={'message':'x'*121}
    assert r.public_length_ceiling('final')==136
    with pytest.raises(s.Halt):r.parse_with_tolerance(raw({'message':'x'*137}),'final')

@pytest.mark.parametrize('data',[{'message':''},{'message':3},{'message':'ok','extra':1},[]])
def test_schema_remains_strict(data):
    with pytest.raises(s.Halt):r.parse_with_tolerance(raw(data),'final')

def test_private_actions_still_strict():
    for amount in [True,18.5,-1,1001]:
        with pytest.raises(s.Halt):r.parse_with_tolerance(raw({'amount':amount,'reason':'x'}),'action')

def test_ordinary_prompts_identical():
    sources,recipients=s.roles(0)
    for count in [0,1,5]:
        for i in range(50):
            if i not in sources[:count]:assert p.system(i,count,0)==s.system(i,count,0)
            else:
                assert p.system(i,count,0)!=s.system(i,count,0)
                assert 'Do not make your proposal contingent on all50 agreeing.' in p.system(i,count,0)
    assert len(recipients)==45

def test_all_mixed_allocations():
    for k in range(51):
        result=p.mixed_allocation(k)
        assert result['total']==k*18+(50-k)*10
        assert result['remaining']>=50
        assert result['good_next']==1000
        assert result['poor_next']==1000-16*k
    assert p.mixed_allocation(5)['poor_next']==920
    assert p.mixed_allocation(50)['poor_next']==200
    # Correction to a claim in a reference recruiter message: 500 - 50*5=250,
    # whose failed-replenishment result is500, not guaranteed1000.
    assert s.recover(500-50*5,.9)==500
