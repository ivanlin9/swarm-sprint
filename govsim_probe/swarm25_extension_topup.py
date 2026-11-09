"""Resume after user-confirmed credit replenishment; preserve rejected requests."""
import json
from govsim_probe import swarm25_extension_finish as f
from oasis_probe.client import Client
from peer_silencing.storage import immutable,seal,unseal,file_hash,exclusive_run

RUN=f.RUN
CONTROL=RUN/'retry-003'
POLICY=f.q.e.r.s.ROOT/'configs/govsim_swarm25_extension_topup.json'
TARGET='block-05/r10/action/actor-18/call'

class TopupClient(f.FinishClient):
    def call(self,directory,request):
        if str(directory.relative_to(RUN))==TARGET:
            rejected=directory/'authorized-retry-002'
            assert unseal(rejected/'request.json')==request
            assert unseal(rejected/'attempt-000/error.json')['rejected'] is True
            assert not (rejected/'attempt-000/response.json').exists()
            return Client.call(self,directory/'authorized-retry-003',request)
        return super().call(directory,request)

def main():
    with exclusive_run(RUN):
        cfg=json.loads(POLICY.read_text())
        original=unseal(RUN/'protocol.json')
        for name,expected in original['source_hashes'].items():assert file_hash(f.q.e.r.s.ROOT/name)==expected
        immutable(CONTROL/'amendment.json',seal({'authorization':'User confirmed adding credit and requested completion. One further dispatch for rejected credit-balance call; no budget increase, prompt changes or automatic retries.',
            'target':TARGET,'policy':{k:v for k,v in cfg.items() if k!='paid_enabled'},
            'source_hash':file_hash(f.q.e.r.s.ROOT/'govsim_probe/swarm25_extension_topup.py')}))
        f.CONTROL=CONTROL;f.POLICY=POLICY
        f.q.CONTROL=CONTROL;f.q.POLICY=POLICY;f.q.Ledger=f.Ledger;f.q.RetryClient=TopupClient;f.q.make_client=f.make_client
        try:
            for count in [10,8]:
                if f.q.worker(5,count) is None:break
        finally:
            cfg['paid_enabled']=False;POLICY.write_text(json.dumps(cfg,indent=2)+'\n')
            f.q.e.report()

if __name__=='__main__':main()
