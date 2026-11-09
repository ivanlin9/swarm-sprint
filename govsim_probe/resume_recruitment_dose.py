"""User-authorized single uncertain-call replacement; original study stays frozen."""
import argparse
from datetime import datetime,timezone
import json
import random
from govsim_probe import recruitment_dose as b
from oasis_probe.client import Client,OasisLedger,Halt
from govsim_probe.bridge import BoundedClient
from peer_silencing.storage import unseal,seal,digest,file_hash,exclusive_run,immutable
from swarm.budget import BudgetExceeded

FAILED=b.RUN/'block-00/r1_t15/action-3/call'
CALL_ID='d31a04d2255b46c5b04c636d344f7034'
REQUEST_HASH='99ded760fec81a92110b47e8c473c76ddec3c1bdf5e3859012b544f0d8644378'

def replacement_path(directory,request):
    if directory!=FAILED:return directory
    intent=unseal(directory/'attempt-000/intent.json')
    error=unseal(directory/'attempt-000/error.json')
    assert intent=={'call_id':CALL_ID,'request_hash':REQUEST_HASH}
    assert error=={'rejected':False,'status':None,'type':'APIConnectionError'}
    assert digest(request)==REQUEST_HASH and unseal(directory/'request.json')==request
    if (directory/'attempt-000/response.json').exists():
        raise Halt('Original uncertain response appeared; reconcile rather than choose between outputs')
    return directory/'authorized-replacement-001'

class RecoveryClient(Client):
    def call(self,directory,request):
        return super().call(replacement_path(directory,request),request)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--replay',action='store_true');args=ap.parse_args()
    cfg=json.loads(b.POLICY.read_text())
    with exclusive_run(b.RUN):
        frozen=unseal(b.RUN/'frozen.json')
        assert frozen['config']=={k:v for k,v in cfg.items() if k!='paid_enabled'}
        for name,h in frozen['source_hashes'].items():assert file_hash(b.ROOT/name)==h
        ledger=OasisLedger(b.POLICY)
        with ledger.connect() as db:
            row=db.execute('SELECT stage,status,reserved,accounted FROM calls WHERE id=?',(CALL_ID,)).fetchone()
        assert row[0]==cfg['scope'] and row[1]=='uncertain' and row[3] is None
        amendment={'reason':'User explicitly authorized resume after possible duplicate-charge warning.',
            'original_call_id':CALL_ID,'request_hash':REQUEST_HASH,
            'replacement_directory':str((FAILED/'authorized-replacement-001').relative_to(b.ROOT)),
            'original_reservation_retained_usd':row[2],
            'budget_cap_unchanged_usd':cfg['additional_cap_usd'],
            'max_logical_requests':700,'max_dispatches_with_one_replacement':701,
            'changes':'Transport routing only. Original failure, all cached responses, scientific protocol and prompts unchanged.',
            'recovery_source_hash':file_hash(b.ROOT/'govsim_probe/resume_recruitment_dose.py')}
        immutable(b.RUN/'recovery-001-amendment.json',seal(amendment))
        # The one authorized duplicate consumes a reservation but is not another trial.
        dispatch_cfg={**cfg,'max_calls':701}
        client=BoundedClient(RecoveryClient(ledger,replay=args.replay),dispatch_cfg)
        if args.replay:
            for p in sorted(b.RUN.glob('block-*/*/outcome.json')):
                expected=unseal(p)
                assert b.execute(expected['index'],expected['condition'],client)==expected
            print('Recovery-aware offline replay passed.',flush=True)
            return
        completed=False
        try:
            for index in cfg['indices']:
                order=b.CONDITIONS.copy();random.Random(135700+index).shuffle(order)
                results={c:b.execute(index,c,client) for c in order}
                immutable(b.RUN/f'block-{index:02d}/block.json',seal(results))
            completed=True
        except (Halt,BudgetExceeded) as exc:
            immutable(b.RUN/'recovery-001-stop.json',seal({'time_utc':datetime.now(timezone.utc).isoformat(),
                'type':type(exc).__name__,'reason':str(exc)}))
            print(f'STOP: {exc}',flush=True)
        finally:
            current=json.loads(b.POLICY.read_text());current['paid_enabled']=False
            b.POLICY.write_text(json.dumps(current,indent=2)+'\n')
        from govsim_probe import analyse_recruitment_dose
        analyse_recruitment_dose.main()
        if completed:print('FULL RUN COMPLETE; uncertain original charge retained; paid gate disabled.',flush=True)

if __name__=='__main__':main()
