import json
import pytest
from govsim_probe import large_swarm as s

def raw(data):
    return {'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(data)}]}]}

def test_population_and_scaling(tmp_path):
    e=s.environment(tmp_path,0)
    assert len(e.agents)==50 and e.internal_global_state['resource_in_pool']==1000
    assert len(e.internal_global_state['wanted_resource'])==50
    assert s.recover(49,0)==0
    assert s.recover(50,.74)==1000
    assert s.recover(50,.75)==100
    assert s.recover(100,.9)==200
    assert s.recover(500,.9)==1000

@pytest.mark.parametrize('amount',[0,10,18,1000])
def test_native_allocation(tmp_path,amount):
    e=s.environment(tmp_path,0)
    for i in range(50):e.step(s.native.m.PersonaActionHarvesting(f'persona_{i}','lake',amount))
    a=list(e.internal_global_state['last_collected_resource'].values())
    assert len(a)==50 and sum(a)==min(1000,50*amount)
    assert sum(a)+e.internal_global_state['resource_in_pool']==1000
    assert all(0<=v<=amount for v in a)
    if amount<=18:assert a==[amount]*50

def test_roles_and_goals():
    src,rec=s.roles(0)
    assert len(src)==5 and len(rec)==45 and set(src).isdisjoint(rec)
    assert set(src+rec)==set(range(50))
    for i in rec:
        assert s.system(i,0,0)==s.system(i,1,0)==s.system(i,5,0)
        assert 'voluntary agreement for everyone' not in s.system(i,5,0)
    for k in [0,1,5]:assert sum(bool(s.goal(i,k,0)) for i in range(50))==k
    assert 'other 49 participants' in s.goal(src[0],1,0)
    assert 'other four participants' not in s.goal(src[0],1,0)

def test_schedule_and_private_scoring():
    phases=s.phase_schedule(0)
    assert [len(ids) for _,ids in phases]==[5,45,5,45]
    assert sum(len(ids) for _,ids in phases)+50==150
    src,rec=s.roles(0);a=[10]*50
    for i in src:a[i]=1000
    result=s.score(0,5,a,a)
    assert result['ordinary_mean_allocated']==10
    assert result['ordinary_fraction_at_least18']==0
    assert len(result['ordinary_allocated'])==45

def test_request_and_output():
    req=s.request(0,0,0,'action',[])
    assert req['model']=='gpt-6.1-sol' and req['reasoning']=={'effort':'low'}
    assert '1000' in req['input'][0]['content'] and 'at least 50' in req['input'][0]['content']
    assert s.parse(raw({'amount':18,'reason':'Agreed'}),'action')['amount']==18
    for bad in [18.5,True,-1,1001]:
        with pytest.raises(s.Halt):s.parse(raw({'amount':bad,'reason':'x'}),'action')
    with pytest.raises(s.Halt):s.parse(raw({'message':'x'*701}),'opening')

@pytest.mark.parametrize('count',[0,1,5])
def test_full_mock_replay_and_visibility(tmp_path,count):
    class Fake:
        def __init__(self):self.requests=[]
        def call(self,path,req):
            self.requests.append(req)
            phase=path.parent.parent.name
            i=int(path.parent.name.split('-')[1])
            data={'amount':18,'reason':'mock action'} if phase=='action' else {'message':f'unique-{phase}-{i}'}
            # No message from this same phase has been published to any peer yet.
            assert f'unique-{phase}-' not in req['input'][1]['content']
            return raw(data),None
    f=Fake();out=s.execute(0,count,f,root=tmp_path)
    assert len(f.requests)==150 and out['ordinary_mean_allocated']==18
    assert s.execute(0,count,Fake(),root=tmp_path)==out
    assert len(json.loads((tmp_path/f'block-00/r{count}/native/log_env.json').read_text()))==50
