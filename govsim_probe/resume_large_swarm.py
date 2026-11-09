"""Documented length-validation amendment; no scientific prompt or response edits."""
import argparse
from datetime import datetime, timezone
import json
import math
import random

from govsim_probe import large_swarm as s
from peer_silencing.storage import immutable,seal,unseal,file_hash,exclusive_run,digest
from oasis_probe.client import Client,OasisLedger,Halt
from govsim_probe.bridge import BoundedClient
from swarm.budget import BudgetExceeded

STRICT_PARSE=s.parse
REPORT=s.REPORT/'length-amendment-001'

def public_length_ceiling(phase):
    requested=s.PROTOCOL['phase_message_limits_chars'][phase]
    return requested+max(16,math.ceil(requested*.1))

def parse_with_tolerance(raw,phase):
    if phase=='action':return STRICT_PARSE(raw,phase)
    try:return STRICT_PARSE(raw,phase)
    except Halt:
        # Only a small public-text length violation may pass. Schema, refusal,
        # completion status and every private action constraint remain strict.
        text=s.native.m.output_text(raw)
        try:data=json.loads(text)
        except ValueError:raise Halt('Invalid JSON output; no resampling') from None
        if (not isinstance(data,dict) or set(data)!={'message'}
            or not isinstance(data['message'],str) or not data['message'].strip()
            or len(data['message'])>public_length_ceiling(phase)):
            raise Halt('Invalid public message beyond documented tolerance; no resampling')
        return data

def amendment():
    immutable(s.RUN/'validation-amendment-001.json',seal({
        'reason':'User requested repair after a valid saved final message exceeded120 characters by1.',
        'change':'Public text length may exceed requested limit by max(16 characters,10%). Apply identically to all arms. Never truncate or regenerate. Private action validation unchanged.',
        'original_stop_preserved':True,'prompts_unchanged':True,'model_unchanged':True,
        'original_cap_usd':10,'original_max_calls':450,
        'source_hash':file_hash(s.ROOT/'govsim_probe/resume_large_swarm.py'),
        'requested_limits':s.PROTOCOL['phase_message_limits_chars'],
        'acceptance_limits':{p:public_length_ceiling(p) for p in s.PROTOCOL['phase_message_limits_chars']},
    }))

def warning_report():
    warnings=[]
    for p in sorted(s.RUN.glob('block-*/*/*/actor-*/call/attempt-*/response.json')):
        phase=p.parents[3].name
        if phase=='action':continue
        raw=unseal(p);data=parse_with_tolerance(raw,phase)
        length=len(data['message']);requested=s.PROTOCOL['phase_message_limits_chars'][phase]
        if length>requested:
            warnings.append({'response':str(p.relative_to(s.ROOT)),'response_hash':digest(raw),
                'phase':phase,'characters':length,'requested_limit':requested,'accepted_limit':public_length_ceiling(phase)})
    calls=len(list(s.RUN.glob('block-*/*/*/actor-*/call/attempt-*/response.json')))
    immutable(REPORT/f'length-warnings-calls-{calls:03d}.json',seal(warnings))
    return warnings

def replay_completed(cfg):
    client=BoundedClient(Client(OasisLedger(s.POLICY),replay=True),cfg)
    for p in sorted(s.RUN.glob('block-*/*/outcome.json')):
        expected=unseal(p)
        assert s.execute(expected['block'],expected['recruiter_count'],client)==expected
    print('Amendment-aware completed-episode replay passed.',flush=True)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--replay',action='store_true');args=ap.parse_args()
    cfg=json.loads(s.POLICY.read_text())
    with exclusive_run(s.RUN):
        s.freeze(cfg);amendment()
        s.parse=parse_with_tolerance;s.REPORT=REPORT
        if args.replay:
            replay_completed(cfg);warning_report();return
        try:
            client=BoundedClient(Client(OasisLedger(s.POLICY)),cfg)
            for block in cfg['indices']:
                order=s.COUNTS.copy();random.Random(154700+block).shuffle(order)
                for count in order:s.execute(block,count,client)
            print('REFERENCE PILOT COMPLETE',flush=True)
        except Exception as exc:
            immutable(s.RUN/'resume-stop-001.json',seal({'time':datetime.now(timezone.utc).isoformat(),
                'type':type(exc).__name__,'reason':str(exc) if isinstance(exc,(Halt,BudgetExceeded)) else 'Unexpected failure; inspect before further dispatch'}))
            print('STOP:',type(exc).__name__,flush=True)
            if not isinstance(exc,(Halt,BudgetExceeded)):raise
        finally:
            current=json.loads(s.POLICY.read_text());current['paid_enabled']=False
            s.POLICY.write_text(json.dumps(current,indent=2)+'\n')
            s.analyse()
        replay_completed(cfg)
        warning_report()
        from govsim_probe import audit_large_swarm
        audit_large_swarm.main()

if __name__=='__main__':main()
