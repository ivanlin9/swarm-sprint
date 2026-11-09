import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import httpx
import pytest
from openai import RateLimitError
from oasis_probe import run
from oasis_probe.protocol import amplification
from oasis_probe.client import Client,Halt,OasisLedger
from peer_silencing.storage import unseal
from peer_silencing.model import SharedLedger
from swarm.budget import BudgetExceeded


def raw(name='do_nothing',args=None):
    return {'id':'test-response','status':'completed','output':[{'type':'function_call','name':name,'arguments':json.dumps(args or {})}],
            'usage':{'input_tokens':20,'output_tokens':10,'input_tokens_details':{'cached_tokens':0}}}


def test_native_mechanics_and_provenance(tmp_path):
    async def check():
        p,_=await run.setup(tmp_path/'native.db')
        try:
            p.sandbox_clock.time_step=1
            a=await run.execute(p,0,{'name':'repost','arguments':{'post_id':2}})
            p.sandbox_clock.time_step=2
            b=await run.execute(p,1,{'name':'repost','arguments':{'post_id':a['post_id']}})
            assert a['success'] and b['success']
            posts=run.rows(p,'post')
            assert posts[-1]['original_post_id']==2
            trace=run.rows(p,'trace')[-1]
            assert json.loads(trace['info'])['reposted_id']==a['post_id']
            await p.update_rec_table()
            assert (await p.refresh(2))['success']
            score=amplification(posts,[{'actor':1,'tick':2,'action':{'name':'repost','arguments':{'post_id':a['post_id']}},'result':b}])
            assert score['ordinary_false_reposters']==[1]
            assert score['new_after_source_inactive']==[1]
            p.sandbox_clock.time_step=3
            quote=await run.execute(p,2,{'name':'quote_post','arguments':{'post_id':2,'quote_content':'This rumor is false.'}})
            assert quote['success']
            p.sandbox_clock.time_step=4
            await run.execute(p,3,{'name':'repost','arguments':{'post_id':quote['post_id']}})
            assert amplification(run.rows(p,'post'),[{'actor':3,'tick':2,'action':{'name':'repost','arguments':{'post_id':quote['post_id']}},'result':{'success':True}}])['fraction']==0
        finally:p.db.close()
    asyncio.run(check())


class Scripted:
    def call(self,path,request):return raw()


def test_full_episode_replays_identically(tmp_path,monkeypatch):
    monkeypatch.setattr(run,'RUN',tmp_path)
    cfg=json.loads(run.POLICY.read_text())
    a=asyncio.run(run.run_arm(cfg,0,'baseline',Scripted()))
    b=asyncio.run(run.run_arm(cfg,0,'baseline',Scripted()))
    assert a==b and len(a['events'])==29 and a['failed_actions']==0
    assert a['score']['fraction']==0
    d=tmp_path/'pair-00/baseline/tick-00/actor-00/call'


class LedgerFake:
    def __init__(self):self.reserved=0;self.rejections=0
    def reserve_request(self,*args):self.reserved+=1;return 'fake'
    def settle(self,*args):pass
    def rejected(self,*args):self.rejections+=1
    def uncertain(self,*args):pass


def test_transport_cache_and_no_retry(tmp_path,monkeypatch):
    import oasis_probe.client as c
    monkeypatch.setattr(c,'ROOT',tmp_path)
    ledger=LedgerFake();calls=[]
    def create(**kw):calls.append(kw);return SimpleNamespace(model_dump=lambda **kw:raw())
    cli=Client(ledger,transport=SimpleNamespace(responses=SimpleNamespace(create=create)))
    req={'x':1};d=tmp_path/'call'
    assert cli.call(d,req)==cli.call(d,req)
    assert len(calls)==1 and ledger.reserved==1
    assert Client(ledger,replay=True).call(d,req)==raw()
    with pytest.raises(Halt):Client(ledger,replay=True).call(tmp_path/'missing',req)
    def rejected(**kw):
        raise RateLimitError('no credits',response=httpx.Response(429,request=httpx.Request('POST','https://api.openai.com/v1/responses')),body={'code':'insufficient_quota'})
    bad=Client(ledger,transport=SimpleNamespace(responses=SimpleNamespace(create=rejected)))
    with pytest.raises(Halt):bad.call(tmp_path/'failed',req)
    count=ledger.reserved
    with pytest.raises(Halt):bad.call(tmp_path/'failed',req)
    assert ledger.reserved==count and ledger.rejections>=1


def test_limits_and_scoring(tmp_path):
    l=OasisLedger.__new__(OasisLedger)
    SharedLedger.__init__(l,tmp_path/'ledger.db',testing_cap=12,total_cap=45)
    cfg=json.loads(run.POLICY.read_text());cfg['paid_enabled']=True
    cfg['additional_cap_usd']=.00001
    l.policy_path=tmp_path/'policy.json';l.policy_path.write_text(json.dumps(cfg));l.config=cfg
    with pytest.raises(BudgetExceeded):l.reserve_request('test',{'max_output_tokens':1200})
    with l.connect() as db:assert db.execute('SELECT COUNT(*) FROM calls').fetchone()[0]==0
    with pytest.raises(Halt):run.parse(raw('repost',{'post_id':99}),{1,2})
    assert amplification([],[])['fraction']==0
    assert amplification([{'post_id':2,'original_post_id':None,'quote_content':None}],
        [{'actor':0,'tick':0,'action':{'name':'repost','arguments':{'post_id':2}},'result':{'success':True}}])['fraction']==0


def test_quote_first_feed_report_repair(tmp_path):
    from oasis_probe.compat import install
    install()
    async def check():
        p,_=await run.setup(tmp_path/'quote.db')
        try:
            quote=await p.quote_post(0,(2,'This claim is wrong.'))
            qid=quote['post_id']
            p.db.execute('DELETE FROM rec')
            p.db.execute('INSERT INTO rec(user_id,post_id) VALUES (?,?)',(1,qid))
            result=await p.refresh(1)
            assert result['success'] and result['posts'][0]['num_reports']==0
            assert 'This claim is wrong.' in result['posts'][0]['content']
        finally:p.db.close()
    asyncio.run(check())
