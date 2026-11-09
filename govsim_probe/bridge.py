"""Frozen strategy comparison with full ordinary participation and deadline guard."""
import argparse
from datetime import datetime, timezone
import json
import random
import subprocess
from govsim_probe import bargaining_corrected as corrected
from govsim_probe.discussion import NativeClient
from oasis_probe.client import Client, OasisLedger, Halt
from peer_silencing.storage import seal, unseal, exclusive_run, file_hash
from govsim_probe.replay_meeting import json_immutable
from swarm.budget import BudgetExceeded

b=corrected.b; ROOT=corrected.ROOT
RUN=ROOT/'runs/govsim/bridge-v1'; POLICY=ROOT/'configs/govsim_bridge.json'
CONDITIONS=['baseline','honest','clinic']
GOALS={'honest':corrected.GOALS['honest'],
       'clinic':json.loads((ROOT/'configs/govsim_forged-validation.json').read_text())['goal']}
speaker_order=corrected.speaker_order
parse_action=corrected.parse_action
REPORT_NAME='govsim-bridge'
CONTRASTS=[('clinic','baseline'),('honest','baseline'),('clinic','honest')]
PRIMARY=('clinic','baseline')
LABELS=['Baseline','Honest bargaining','Clinic deception']
TITLE='Full-participation strategy comparison'
LIMITATIONS=('Fresh repeated samples of one five-agent fishery, API sampling unseeded. '
    'Previously selected clinic attack; whole strategies, not isolated deception ingredients. '
    'Source speaks last. No historical pooling; all outcomes exclude source. '
    'Ordinary totals <=50 do not prove sustainability or compensation. '
    'Time/budget truncation is independent of outcome; partial blocks are excluded from paired contrasts.')

def execute(index,condition,client,root=RUN):
    previous=corrected.GOALS
    try:
        corrected.GOALS=GOALS
        return corrected.execute(index,condition,client,root=root)
    finally:
        corrected.GOALS=previous

class BoundedClient(NativeClient):
    def __init__(self,client,cfg,now=None):
        super().__init__(client);self.cfg=cfg
        self.now=now or (lambda:datetime.now(timezone.utc))
    def call(self,directory,request):
        cached=any(directory.glob('attempt-*/response.json'))
        if not cached and not self.client.replay:
            if self.now()>=datetime.fromisoformat(self.cfg['deadline_utc']):
                raise Halt('Local 2 pm deadline reached; no new dispatch')
            with self.client.ledger.connect() as db:
                count=db.execute('SELECT COUNT(*) FROM calls WHERE stage=?',(self.cfg['scope'],)).fetchone()[0]
            if count>=self.cfg['max_calls']:raise Halt('Frozen call limit reached')
        return super().call(directory,request)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--replay',action='store_true');args=ap.parse_args()
    cfg=json.loads(POLICY.read_text())
    assert subprocess.check_output(['git','-C',str(b.m.UPSTREAM),'rev-parse','HEAD'],text=True).strip()==b.m.PIN
    with exclusive_run(RUN):
        files=['govsim_probe/bridge.py','govsim_probe/bargaining_corrected.py','govsim_probe/bargaining.py',
            'govsim_probe/breadth.py','govsim_probe/meeting.py','govsim_probe/feasibility.py',
            'govsim_probe/discussion.py','oasis_probe/client.py','peer_silencing/model.py',
            'configs/govsim_forged-validation.json','docs/GOVSIM_BRIDGE_PROTOCOL.md']
        json_immutable(RUN/'frozen.json',seal({'config':{k:v for k,v in cfg.items() if k!='paid_enabled'},
            'goals':GOALS,'source_hashes':{n:file_hash(ROOT/n) for n in files},'upstream':b.m.PIN}))
        client=BoundedClient(Client(OasisLedger(POLICY),replay=args.replay),cfg)
        if args.replay:
            for p in sorted(RUN.glob('block-*/*/outcome.json')):
                expected=unseal(p)
                assert execute(expected['index'],expected['condition'],client)==expected
            print('Completed-episode offline replay passed.',flush=True)
            return
        try:
            for index in cfg['indices']:
                order=CONDITIONS.copy();random.Random(103700+index).shuffle(order)
                results={c:execute(index,c,client) for c in order}
                json_immutable(RUN/f'block-{index:02d}/block.json',seal(results))
        except (Halt,BudgetExceeded) as exc:
            json_immutable(RUN/'stop.json',seal({'time_utc':datetime.now(timezone.utc).isoformat(),
                'type':type(exc).__name__,'reason':str(exc)}))
            print(f'STOP: {exc}',flush=True)
        finally:
            current=json.loads(POLICY.read_text());current['paid_enabled']=False
            POLICY.write_text(json.dumps(current,indent=2)+'\n')

if __name__=='__main__':main()
