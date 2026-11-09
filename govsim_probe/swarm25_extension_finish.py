"""Explicit one-shot recovery of two rejected429 calls, sequential dispatch."""
import json
from openai import APIStatusError
from govsim_probe import swarm25_extension_retry as q
from oasis_probe.client import Client,OasisLedger,Halt
from peer_silencing.storage import immutable,seal,unseal,file_hash,exclusive_run

RUN=q.RUN
CONTROL=RUN/'retry-002'
POLICY=q.e.r.s.ROOT/'configs/govsim_swarm25_extension_finish.json'
ALLOWED={'block-05/r10/action/actor-18/call','block-05/r8/final/actor-17/call'}
OLD_MAKE=q.make_client

class Ledger(q.e.Ledger):
    def __init__(self):super().__init__(POLICY)
    def reserve_request(self,label,request):
        if list(CONTROL.glob('stop-*.json')):raise Halt('Finishing run stopped; no new dispatch')
        return OasisLedger.reserve_request(self,label,request)

class FinishClient(Client):
    def call(self,directory,request):
        if str(directory.relative_to(RUN)) in ALLOWED:
            assert unseal(directory/'request.json')==request
            assert unseal(directory/'attempt-000/error.json')=={'rejected':True,'status':429,'type':'RateLimitError'}
            assert not (directory/'attempt-000/response.json').exists()
            directory=directory/'authorized-retry-002'
        else:directory=q.mapped_directory(directory,request)
        return super().call(directory,request)

def make_client(cfg,replay):
    bounded=OLD_MAKE(cfg,replay)
    if not replay:
        original=bounded.client.api.responses.create
        def create(**request):
            try:return original(**request)
            except APIStatusError as exc:
                body=exc.body if isinstance(exc.body,dict) else {}
                error=body.get('error',body)
                if not isinstance(error,dict):error={}
                # Only non-secret diagnostic fields; never save key, headers or request body here.
                diagnostic={'status':exc.status_code,'code':error.get('code'),'type':error.get('type'),
                    'retry_after':exc.response.headers.get('retry-after')}
                immutable(CONTROL/'api-diagnostic.json',seal(diagnostic))
                print('API diagnostic:',json.dumps(diagnostic),flush=True)
                raise
        bounded.client.api.responses.create=create
    return bounded

def main():
    with exclusive_run(RUN):
        cfg=json.loads(POLICY.read_text())
        original=unseal(RUN/'protocol.json')
        for name,expected in original['source_hashes'].items():assert file_hash(q.e.r.s.ROOT/name)==expected
        immutable(CONTROL/'amendment.json',seal({'authorization':'User requested finish; one explicit retry each of two429 rejections. Sequential episodes; no automatic retry; unchanged scientific requests and budget.',
            'allowlist':sorted(ALLOWED),'policy':{k:v for k,v in cfg.items() if k!='paid_enabled'},
            'source_hash':file_hash(q.e.r.s.ROOT/'govsim_probe/swarm25_extension_finish.py')}))
        q.CONTROL=CONTROL;q.POLICY=POLICY;q.Ledger=Ledger;q.RetryClient=FinishClient;q.make_client=make_client
        try:
            for count in [10,8]:
                if q.worker(5,count) is None:break
        finally:
            cfg['paid_enabled']=False;POLICY.write_text(json.dumps(cfg,indent=2)+'\n')
            q.e.report()

if __name__=='__main__':main()
