"""User-authorized single retry of three saved timeouts; original artifacts retained."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime,timezone
import json
import multiprocessing
from dotenv import dotenv_values
from openai import OpenAI
from govsim_probe import swarm25_extension as e
from oasis_probe.client import Client,OasisLedger,Halt
from peer_silencing.storage import immutable,seal,unseal,file_hash,exclusive_run,digest

RUN=e.RUN
CONTROL=RUN/'retry-001'
POLICY=e.r.s.ROOT/'configs/govsim_swarm25_extension_retry.json'
ALLOWED={
 'block-04/r0/confirmation/actor-17/call',
 'block-04/r10/response/actor-02/call',
 'block-04/r8/confirmation/actor-16/call',
}

class Ledger(e.Ledger):
    def __init__(self):super().__init__(POLICY)
    def reserve_request(self,label,request):
        if list(CONTROL.glob('stop-*.json')):raise Halt('Retry run halted; no new dispatch')
        return OasisLedger.reserve_request(self,label,request)

def mapped_directory(directory,request):
    relative=str(directory.relative_to(RUN))
    if relative not in ALLOWED:return directory
    error=unseal(directory/'attempt-000/error.json')
    assert error=={'rejected':False,'status':None,'type':'APITimeoutError'}
    assert not (directory/'attempt-000/response.json').exists()
    assert unseal(directory/'request.json')==request
    return directory/'authorized-retry-001'

class RetryClient(Client):
    def call(self,directory,request):
        return super().call(mapped_directory(directory,request),request)

def make_client(cfg,replay):
    transport=None
    if not replay:
        keys=dotenv_values(e.r.s.ROOT/'.env',interpolate=False)
        transport=OpenAI(api_key=keys.get('OPENAI_API_KEY'),organization=keys.get('OPENAI_ORG_ID') or None,
            project=keys.get('OPENAI_PROJECT_ID') or None,base_url='https://api.openai.com/v1',max_retries=0,timeout=180)
    return e.r.BoundedClient(RetryClient(Ledger(),replay=replay,transport=transport),cfg)

def worker(block,count,replay=False):
    cfg=json.loads(POLICY.read_text())
    with e.r.h.context():
        try:
            result=e.r.s.execute(block,count,make_client(cfg,replay),root=RUN)
            assert e.r.s.execute(block,count,make_client(cfg,True),root=RUN)==result
            immutable(CONTROL/f'audit-b{block}-r{count}.json',seal({'block':block,'count':count,'offline_replay_passed':True}))
            return result
        except Exception as exc:
            if not replay:
                immutable(CONTROL/f'stop-b{block}-r{count}.json',seal({'type':type(exc).__name__,
                    'time':datetime.now(timezone.utc).isoformat(),'reason':'Stopped; no automatic retry. Inspect saved error.'}))
            print(f'block={block} count={count} STOP {type(exc).__name__}',flush=True)
            return None

def freeze(cfg):
    original=unseal(RUN/'protocol.json')
    for name,expected in original['source_hashes'].items():assert file_hash(e.r.s.ROOT/name)==expected
    records={}
    for rel in sorted(ALLOWED):
        directory=RUN/rel;request=unseal(directory/'request.json')
        mapped_directory(directory,request)
        intent=unseal(directory/'attempt-000/intent.json')
        with Ledger().connect() as db:
            status=db.execute('SELECT status FROM calls WHERE id=?',(intent['call_id'],)).fetchone()[0]
        assert status=='uncertain'
        records[rel]={'original_intent':intent,'request_hash':digest(request)}
    immutable(CONTROL/'amendment.json',seal({'authorization':'User explicitly requested retry of saved timeouts. One new dispatch per listed timeout; retain original uncertain charges.',
        'allowlist':records,'timeout_seconds':180,'sdk_retries':0,'scientific_prompts_unchanged':True,
        'policy':{k:v for k,v in cfg.items() if k!='paid_enabled'},
        'source_hash':file_hash(e.r.s.ROOT/'govsim_probe/swarm25_extension_retry.py')}))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--replay',action='store_true');args=ap.parse_args()
    with exclusive_run(RUN):
        cfg=json.loads(POLICY.read_text());freeze(cfg)
        if args.replay:
            for p in sorted(RUN.glob('block-*/*/outcome.json')):
                row=unseal(p);assert worker(row['block'],row['recruiter_count'],True)==row
            return
        try:
            with ProcessPoolExecutor(max_workers=3,mp_context=multiprocessing.get_context('spawn')) as pool:
                futures=[pool.submit(worker,b,c) for b,c in e.r.jobs(cfg)]
                for future in futures:future.result()
        finally:
            cfg['paid_enabled']=False;POLICY.write_text(json.dumps(cfg,indent=2)+'\n')
            e.report()

if __name__=='__main__':main()
