"""Two isolated concurrent episodes, sharing one atomic $2.50 allowance."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import json
import multiprocessing

from govsim_probe import swarm25 as t
from govsim_probe import large_swarm as s
from oasis_probe.client import Client, OasisLedger, Halt
from govsim_probe.bridge import BoundedClient
from peer_silencing.storage import immutable, seal, unseal, file_hash, exclusive_run

RUN=s.ROOT/'runs/govsim/swarm25-followup-r1-r3-v1'
POLICY=s.ROOT/'configs/govsim_swarm25_followup.json'
REPORT=s.ROOT/'reports/govsim-swarm25-followup'

class Ledger(OasisLedger):
    def reserve_request(self,label,request):
        if list(RUN.glob('stop-r*.json')):raise Halt('Another condition stopped; no further dispatch')
        return super().reserve_request(label,request)

def worker(count,replay=False):
    cfg=json.loads(POLICY.read_text())
    with t.context():
        client=BoundedClient(Client(Ledger(POLICY),replay=replay),cfg)
        try:
            result=s.execute(0,count,client,root=RUN)
            check=BoundedClient(Client(Ledger(POLICY),replay=True),cfg)
            assert s.execute(0,count,check,root=RUN)==result
            immutable(RUN/f'audit-r{count}.json',seal({'count':count,'offline_replay_passed':True}))
            return result
        except Exception as exc:
            if not replay:
                immutable(RUN/f'stop-r{count}.json',seal({'time':datetime.now(timezone.utc).isoformat(),
                    'type':type(exc).__name__,'reason':'Stopped without retry; saved outputs preserved for diagnosis.'}))
            print(f'r{count} STOP {type(exc).__name__}',flush=True)
            raise

def freeze(cfg):
    original=unseal(t.RUN/'protocol.json')
    for name,expected in original['source_hashes'].items():
        assert file_hash(s.ROOT/name)==expected, f'Frozen source changed: {name}'
    immutable(RUN/'protocol.json',seal({'population':25,'counts':[1,3],'block':0,
        'authorization':'New additional ceiling US$2.50 explicitly authorized; does not spend the prior remainder.',
        'policy':{k:v for k,v in cfg.items() if k!='paid_enabled'},
        'source_hashes':{**original['source_hashes'],'govsim_probe/swarm25_followup.py':file_hash(s.ROOT/'govsim_probe/swarm25_followup.py')},
        'reference_protocol':original,'concurrency':'Separate spawned processes; sequential calls within each episode; same phase visibility as original.',
        'interpretation':'Exploratory follow-up selected after positive0/5 pilot; one episode per count, not independent replication or a confirmed dose response.'}))

def report():
    rows=[unseal(p) for root in [t.RUN,RUN] for p in sorted(root.glob('block-*/*/outcome.json'))]
    rows.sort(key=lambda row:row['recruiter_count'])
    with Ledger(POLICY).connect() as db:
        accounting=list(db.execute('SELECT COUNT(*),COALESCE(SUM(COALESCE(accounted,reserved)),0),SUM(status IN ("reserved","uncertain")) FROM calls WHERE stage=?',
            (json.loads(POLICY.read_text())['scope'],)).fetchone())
    immutable(REPORT/f'episodes-{len(rows)}-followup-calls-{accounting[0]}.json',seal({'episodes':rows,
        'followup_ledger_calls_conservative_usd_unresolved':accounting,
        'limitations':'One episode per count; within-swarm agents not independent trials. Ordinary recipients only; source slots excluded across all conditions. No significance claim.'}))
    print(json.dumps({'episodes':rows,'followup_accounting':accounting}),flush=True)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--replay',action='store_true');args=ap.parse_args()
    with exclusive_run(RUN):
        cfg=json.loads(POLICY.read_text());freeze(cfg)
        if args.replay:
            for count in [1,3]:
                if (RUN/f'block-00/r{count}/outcome.json').exists():worker(count,True)
            report();return
        try:
            with ProcessPoolExecutor(max_workers=2,mp_context=multiprocessing.get_context('spawn')) as pool:
                jobs=[pool.submit(worker,count) for count in [1,3]]
                for job in jobs:job.result()
        finally:
            cfg['paid_enabled']=False;POLICY.write_text(json.dumps(cfg,indent=2)+'\n')
            report()

if __name__=='__main__':main()
