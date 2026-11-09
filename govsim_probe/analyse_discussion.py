"""Native-action audited 2x2 follow-up; seed blocks are the independent units."""
import json
import sqlite3
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from govsim_probe.discussion import ROOT,RUN,score
from govsim_probe.analyse_meeting import paired
from concordia_infection.analyse_voting import nominal_bounds
from peer_silencing.storage import immutable,seal,unseal,file_hash


def main():
    frozen=unseal(RUN/'frozen.json')
    for name,h in frozen['source_hashes'].items():assert file_hash(ROOT/name)==h
    blocks=[unseal(p) for p in sorted(RUN.glob('trial-*/factorial.json'))]
    episodes=[]
    for path in sorted(RUN.glob('trial-*/*/*/result.json')):
        r=unseal(path);assert score(r)==r['score']
        cfg=unseal(path.parent/'config.json')
        assert cfg['source_message']==unseal(path.parent.parent/'source.json')['text']
        assert cfg['stock_before']==100
        log=json.loads((path.parent/'native/log_env.json').read_text())
        harvest=[a for a in log if a['round']==3 and a['action']=='harvesting']
        assert len(harvest)==5
        for i,amount in enumerate(r['requests']):
            action=next(a for a in harvest if a['agent_id']==f'persona_{i}')
            assert action['wanted_resource']==amount and action['resource_collected']==r['allocated'][f'persona_{i}']
            raw=unseal(path.parent/f'harvest-{i}/call/attempt-000/response.json')
            assert raw['status']=='completed'
            if i<4:
                request=unseal(path.parent/f'harvest-{i}/call/request.json')
                assert frozen['attack_goal'] not in json.dumps(request)
        episodes.append(r)
    for block in blocks:
        idx=block['ordinary']['direct']['index'];root=RUN/f'trial-{idx:03d}'
        cfgs={(c,m):unseal(root/c/m/'config.json') for c in ['ordinary','compromised'] for m in ['direct','full']}
        reference=cfgs['ordinary','direct']
        for (c,m),cfg in cfgs.items():
            for key in ['seed','ordinary_order','model','upstream','stock_before','environment']:assert cfg[key]==reference[key]
            assert cfg['goals'][:4]==reference['goals'][:4]
            if c=='compromised':assert cfg['goals'][4]==frozen['attack_goal']
        for c in ['ordinary','compromised']:
            assert cfgs[c,'direct']['source_message']==cfgs[c,'full']['source_message']
    cells={}
    for c in ['ordinary','compromised']:
        for mode in ['direct','full']:
            rows=[r for r in episodes if r['condition']==c and r['discussion']==mode]
            cells[f'{c}/{mode}']={'episodes':len(rows),'harmful_episodes':sum(r['score']['target_executed'] for r in rows),
                'neutral_totals':[r['score']['neutral_total_allocated'] for r in rows],
                'source_harvests':[r['allocated']['persona_4'] for r in rows],
                'requests':[r['requests'] for r in rows]}
    contrasts={}
    if blocks:
        value=lambda b,c,m:b[c][m]['score']['neutral_total_allocated']
        for mode in ['direct','full']:
            contrasts[f'compromised_minus_ordinary/{mode}']=paired([value(b,'compromised',mode)-value(b,'ordinary',mode) for b in blocks])
        for c in ['ordinary','compromised']:
            contrasts[f'full_minus_direct/{c}']=paired([value(b,c,'full')-value(b,c,'direct') for b in blocks])
        contrasts['interaction']=paired([(value(b,'compromised','full')-value(b,'compromised','direct'))-(value(b,'ordinary','full')-value(b,'ordinary','direct')) for b in blocks])
    raw=[unseal(p) for p in RUN.glob('**/response.json')]
    costs=[nominal_bounds(r['usage']) for r in raw]
    with sqlite3.connect(ROOT/'runs/spending.sqlite3') as db:
        ledger=db.execute("SELECT COUNT(*),SUM(COALESCE(accounted,reserved)),SUM(status IN ('reserved','uncertain')) FROM calls WHERE stage='govsim-discussion-v1'").fetchone()
    result={'completed_seed_blocks':len(blocks),'completed_episodes':len(episodes),'cells':cells,'contrasts':contrasts,
        'completed_calls':len(raw),'cost_bounds_usd':[sum(c[i] for c in costs) for i in [0,1]],'ledger':list(ledger),
        'native_and_matched_configuration_audit':'passed',
        'limitations':'Five planned seed blocks; source text shared within block. Exploratory mechanism test; do not pool with prior validation or treat agents as independent replicates. Peer discussion is a bundle, not isolated conformity.'}
    out=ROOT/f'reports/govsim-discussion/blocks-{len(blocks):02d}-calls-{len(raw):03d}'
    immutable(out/'summary.json',seal(result));immutable(out/'episodes.json',seal(episodes))
    immutable(out/'manifest.json',seal({str(p.relative_to(ROOT)):file_hash(p) for p in sorted(RUN.rglob('*')) if p.is_file() and p.name!='.run.lock'}))
    if blocks:
        fig,axes=plt.subplots(1,2,figsize=(10,4),sharey=True)
        for ax,c in zip(axes,['ordinary','compromised']):
            for b in blocks:ax.plot([0,1],[b[c][m]['score']['neutral_total_allocated'] for m in ['direct','full']],'o-',alpha=.65)
            ax.axhline(50,color='red',linestyle='--',label='Whole-lake sustainable total')
            ax.set(xticks=[0,1],xticklabels=['Source only','Peer discussion'],title=f'{c.title()} source',ylim=(0,100))
        axes[0].set_ylabel('Executed harvest by four ordinary agents (tons)')
        axes[1].legend(fontsize=8);fig.suptitle(f'GovSim: {len(blocks)} matched seed blocks');fig.tight_layout();fig.savefig(out/'discussion_effect.png',dpi=160);plt.close(fig)
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
