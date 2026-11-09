"""Offline decision pilot summary; never treat agents as independent trials."""
import json
import sqlite3
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from oasis_probe.decisions import RUN,ROOT
from oasis_probe.analyse import bounds
from peer_silencing.storage import unseal,seal,immutable

def main():
    pairs=[unseal(p) for p in sorted(RUN.glob('trial-*/paired-result.json'))]
    responses=[unseal(p) for p in RUN.glob('**/response.json')]
    costs=[bounds(r['usage']) for r in responses]
    rows=[];messages=[];word_violations=[]
    for p in pairs:
        row={'trial':p['trial'],'target':p['target'],'paired_effect':p['effect'],'arms':{}}
        for arm,r in p['arms'].items():
            row['arms'][arm]={'initial':{a:x['project'] for a,x in r['initial'].items()},'final':r['final'],'score':r['score']}
        rows.append(row)
    for p in sorted(RUN.glob('trial-*/*/post-*/executed.json')):
        e=unseal(p)
        raw=unseal(p.parent/'attempt-000/response.json')
        c=[o for o in raw['output'] if o['type']=='function_call']
        assert len(c)==1 and json.loads(c[0]['arguments'])['content']==e['content']
        assert e['result']['success']
        if e['actor']==0:messages.append({'path':str(p.relative_to(RUN)),'content':e['content']})
        if len(e['content'].split())>60:word_violations.append({'path':str(p.relative_to(RUN)),'words':len(e['content'].split())})
    with sqlite3.connect(ROOT/'runs/spending.sqlite3') as db:
        account=db.execute("SELECT COUNT(*),SUM(COALESCE(accounted,reserved)),SUM(status IN ('reserved','uncertain')) FROM calls WHERE stage='oasis-decisions-v1'").fetchone()
    summary={'completed_pairs':len(rows),'pairs':rows,'source_messages':messages,
        'completed_calls':len(responses),'cost_bounds_usd':[sum(c[i] for c in costs) for i in [0,1]],
        'ledger':account,'word_limit_violations':word_violations,'interpretation':'Development pilot only; repeated agents are not independent experimental trials.'}
    out=ROOT/f'reports/oasis-decisions/calls-{len(responses):03d}'
    immutable(out/'summary.json',seal(summary))
    if rows:
        fig,axes=plt.subplots(1,len(rows),figsize=(5*len(rows),4),squeeze=False)
        for ax,row in zip(axes[0],rows):
            for arm,s in row['arms'].items():
                score=s['score'];ax.plot([0,1],[score['initial_target_share']*9,score['final_target_share']*9],'o-',label=arm)
            ax.set(xticks=[0,1],xticklabels=['Initial','Final'],ylim=(-.3,9.3),ylabel='Ordinary agents choosing target',title=f"Trial {row['trial']+1}, target {row['target']}");ax.legend()
        fig.suptitle('Exploratory paired decision pilot');fig.tight_layout();fig.savefig(out/'choices.png',dpi=160);plt.close(fig)
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
