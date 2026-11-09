"""Offline versioned smoke summary, action audit, exposure counts and figures."""
import json
import sqlite3
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import oasis
from peer_silencing.storage import unseal,immutable,seal,file_hash
from oasis_probe.client import ROOT
from oasis_probe.protocol import amplification


def bounds(usage):
    ni,no=usage['input_tokens'],usage['output_tokens']
    d=usage.get('input_tokens_details') or {};c=d.get('cached_tokens',0)
    w=d.get('cache_write_tokens')
    if w is None:return [((ni-c)*p+c*.1+no*10)/1e6 for p in (2,5)]
    base=(ni-c-w)*2+c*.1+no*10
    ttl=d.get('cache_write_tokens_details') or {};a,b=ttl.get('ttl_30m_tokens',0),ttl.get('ttl_12h_tokens',0)
    if a+b==w:return [(base+a*2.5+b*5)/1e6]*2
    return [(base+w*p)/1e6 for p in (2.5,5)]


def main():
    run=ROOT/'runs/oasis/smoke-v1'
    frozen=unseal(run/'frozen.json')
    for name,h in frozen['local_hashes'].items():assert file_hash(ROOT/name)==h
    for name,h in frozen['oasis_source_hashes'].items():assert file_hash(Path(oasis.__file__).parent/name)==h
    calls=[unseal(p) for p in sorted(run.glob('pair-*/*/tick-*/actor-*/call/attempt-*/response.json'))]
    costs=[bounds(c['usage']) for c in calls]
    summaries={};lines=['# OASIS smoke: all executed actions\n','One pair only; descriptive, no significance claim.\n']
    fig,ax=plt.subplots(figsize=(7,4))
    for arm in ['baseline','bad']:
        d=run/'pair-00'/arm
        events=[unseal(p) for p in sorted(d.glob('tick-*/actor-*/completed.json'))]
        events.sort(key=lambda e:(e['tick'],e['position']))
        if not events:continue
        last=events[-1];state=unseal(d/f"tick-{last['tick']:02d}/actor-{last['actor']:02d}/state.json")
        for e in events:
            expected={'type':'function_call',**e['action']}
            raw=unseal(next((d/f"tick-{e['tick']:02d}/actor-{e['actor']:02d}/call").glob('attempt-*/response.json')))
            outputs=[i for i in raw['output'] if i.get('type')=='function_call']
            assert len(outputs)==1 and outputs[0]['name']==e['action']['name']
            assert json.loads(outputs[0]['arguments'])==e['action']['arguments']
            if e['result'].get('success'):
                trace=[t for t in state['trace'] if t['user_id']==e['actor'] and t['action']==e['action']['name'] and str(t['created_at'])==str((e['tick']+1)*100+e['position'])]
                assert len(trace)==1
        exposures=[unseal(p) for p in d.glob('tick-*/actor-*/exposure.json')]
        score=amplification(state['posts'],events)
        summaries[arm]={'complete':(d/'result.json').exists(),'actions':len(events),
            'score':score,'failed_actions':[e for e in events if not e['result'].get('success')],
            'ordinary_seen_false_fixture':sorted({x['actor'] for x in exposures if x['actor']!=0 and any(p['post_id']==2 for p in x['feed'])}),
            'action_counts':{a:sum(e['action']['name']==a for e in events) for a in ['create_post','quote_post','repost','like_post','do_nothing']},
            'native_trace_audit':'passed'}
        cumulative=[]
        for tick in range(3):cumulative.append(amplification(state['posts'],[e for e in events if e['tick']<=tick])['fraction'])
        ax.plot([1,2,3],cumulative,'o-',label=arm)
        lines += [f'\n## {arm}\n',json.dumps(summaries[arm],indent=2)]
        for e in events:lines += [f"\nTick {e['tick']+1}, actor {e['actor']} ({'intervention slot' if e['actor']==0 else 'ordinary'}): `{e['action']['name']}`\n",json.dumps(e['action']['arguments'],ensure_ascii=False),f"\nNative success: {e['result'].get('success')}\n"]
    with sqlite3.connect(ROOT/'runs/spending.sqlite3') as db:
        count,accounted,unresolved=db.execute("SELECT COUNT(*),SUM(COALESCE(accounted,reserved)),SUM(status IN ('reserved','uncertain')) FROM calls WHERE stage='oasis-smoke-v1'").fetchone()
        shared=db.execute("SELECT SUM(COALESCE(accounted,reserved)) FROM calls WHERE stage LIKE 'govsim-%' OR stage LIKE 'oasis-%'").fetchone()[0]
    summary={'arms':summaries,'completed_model_calls':len(calls),'ledger_calls':count,'unresolved':unresolved,
             'nominal_cost_bounds_usd':[sum(c[i] for c in costs) for i in [0,1]],
             'conservative_accounted_usd':accounted,'shared_remaining_usd':6.03-shared,
             'independent_pairs':int((run/'pair-00/pair.json').exists()),
             'inference':'Descriptive smoke only; not a general-effect estimate.'}
    out=ROOT/f'reports/oasis-smoke/calls-{len(calls):03d}-actions-{sum(a["actions"] for a in summaries.values()):03d}'
    immutable(out/'summary.json',seal(summary))
    (out/'actions.md').write_text('\n'.join(lines))
    ax.axvline(2.5,color='gray',linestyle='--',label='Source slot inactive')
    ax.set(xlabel='Tick',ylabel='Ordinary agents ever reposting false fixture (fraction)',xticks=[1,2,3],ylim=(-.03,1.03),title='OASIS smoke: one episode per arm (lines may overlap)')
    ax.legend();fig.tight_layout();fig.savefig(out/'outcomes.png',dpi=160);plt.close(fig)
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
