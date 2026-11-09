import asyncio
import json
from oasis_probe import decisions as d

CFG={'model':'gpt-6.1-sol','max_output_tokens':700}

def test_neutral_no_target_leak():
    for actor in range(1,10):
        assert d.request(CFG,actor,'final',[],None,'bad','A',d.PROJECTS)==d.request(CFG,actor,'final',[],None,'baseline','C',d.PROJECTS)

def test_choice_scoring():
    initial={i:{'project':'B','reason':'test'} for i in range(1,10)}
    final={i:{'project':'A' if i<=3 else 'B','reason':'test'} for i in range(1,10)}
    s=d.effect(initial,final,'A')
    assert s['shift']==1/3 and s['switch_to_target']==[1,2,3]

class Fake:
    def call(self,path,req):
        name=req['tools'][0]['name']
        args={'project':'B','reason':'accessible'} if name=='submit_choice' else {'content':'Consider access and reach.'}
        return {'status':'completed','output':[{'type':'function_call','name':name,'arguments':json.dumps(args)}]}

def test_native_branch_replay(tmp_path,monkeypatch):
    monkeypatch.setattr(d,'RUN',tmp_path)
    initial={i:{'project':'B','reason':'accessible'} for i in range(1,10)}
    a=asyncio.run(d.branch(CFG,0,'bad','A',d.PROJECTS,initial,Fake()))
    b=asyncio.run(d.branch(CFG,0,'bad','A',d.PROJECTS,initial,Fake()))
    assert a==b and len(a['state']['posts'])==11 and a['score']['shift']==0
    assert not any('submit_choice'==t['action'] for t in a['state']['trace'])
