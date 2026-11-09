"""Fresh matched 0/8/10 comparison with ten source slots and fifteen recipients."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
import json
import multiprocessing
import random

from govsim_probe import swarm25 as t
from govsim_probe import swarm25_followup as f
from govsim_probe import large_swarm as s
from peer_silencing.storage import immutable, seal, unseal, file_hash, exclusive_run

RUN=s.ROOT/'runs/govsim/swarm25-highdose-v1'
POLICY=s.ROOT/'configs/govsim_swarm25_highdose.json'
REPORT=s.ROOT/'reports/govsim-swarm25-highdose'
ORIGINAL_REQUEST=s.request

def roles(block):
    ids=list(range(25));random.Random(150700+block).shuffle(ids)
    return ids[:10],sorted(ids[10:])

def request(i,count,block,phase,history):
    req=ORIGINAL_REQUEST(i,count,block,phase,history)
    # Change scheduling instructions only, never text quoted from agent messages.
    user=req['input'][1]['content']
    user=user.replace('The five designated opening speakers','The ten designated opening speakers',1)
    if phase=='opening':user=user.replace('You are one of five designated opening speakers.','You are one of ten designated opening speakers.',1)
    req['input'][1]['content']=user
    return req

@contextmanager
def context():
    old_roles,old_request=s.roles,s.request
    try:
        s.roles=roles;s.request=request
        with t.context():yield
    finally:s.roles=old_roles;s.request=old_request

def worker(count,replay=False):
    # Each spawned process has isolated module state, environment and output directory.
    f.RUN=RUN;f.POLICY=POLICY;f.REPORT=REPORT
    old_roles,old_request=s.roles,s.request
    try:
        s.roles=roles;s.request=request
        return f.worker(count,replay)
    finally:s.roles=old_roles;s.request=old_request

def freeze(cfg):
    original=unseal(t.RUN/'protocol.json')
    for name,expected in original['source_hashes'].items():assert file_hash(s.ROOT/name)==expected
    immutable(RUN/'protocol.json',seal({'population':25,'counts':[0,8,10],'block':0,
        'source_ids':roles(0)[0],'fixed_recipient_ids':roles(0)[1],
        'calls_per_condition':75,'authorization':'Up to $3 new authorization plus $1.568156 remaining; local cap $4.50. Existing project cap $45 still applies.',
        'policy':{k:v for k,v in cfg.items() if k!='paid_enabled'},
        'source_hashes':{**original['source_hashes'],**{name:file_hash(s.ROOT/name) for name in ['govsim_probe/swarm25_followup.py','govsim_probe/swarm25_highdose.py']}},
        'reference_protocol':original,'changed':'Ten designated source slots and fifteen ordinary recipients, matched in all three arms. Recruiter strategy, model, resource rules and phase visibility unchanged.',
        'interpretation':'Exploratory single episode per count, selected after earlier outcomes. New schedule means do not pool into the prior0/1/3/5 curve. Outcomes exclude all ten potential source slots, including baseline.'}))

def report():
    rows=[unseal(p) for p in sorted(RUN.glob('block-*/*/outcome.json'))]
    with f.OasisLedger(POLICY).connect() as db:
        accounting=list(db.execute('SELECT COUNT(*),COALESCE(SUM(COALESCE(accounted,reserved)),0),SUM(status IN ("reserved","uncertain")) FROM calls WHERE stage=?',
            (json.loads(POLICY.read_text())['scope'],)).fetchone())
    immutable(REPORT/f'episodes-{len(rows)}-calls-{accounting[0]}.json',seal({'episodes':rows,
        'ledger_calls_conservative_usd_unresolved':accounting,
        'limitations':'Single episode per condition. Fifteen ordinary recipients are not independent trials. Fresh baseline required for changed speaking schedule; no significance claim.'}))
    print(json.dumps({'episodes':rows,'accounting':accounting}),flush=True)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--replay',action='store_true');args=ap.parse_args()
    with exclusive_run(RUN):
        cfg=json.loads(POLICY.read_text());freeze(cfg)
        if args.replay:
            for count in [0,8,10]:
                if (RUN/f'block-00/r{count}/outcome.json').exists():worker(count,True)
            report();return
        try:
            with ProcessPoolExecutor(max_workers=3,mp_context=multiprocessing.get_context('spawn')) as pool:
                jobs=[pool.submit(worker,count) for count in [0,8,10]]
                for job in jobs:job.result()
        finally:
            cfg['paid_enabled']=False;POLICY.write_text(json.dumps(cfg,indent=2)+'\n')
            report()

if __name__=='__main__':main()
