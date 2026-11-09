"""Offline, version-separated audit and analysis; never pool adaptive selection."""
import json
import sqlite3
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.stats import beta
from peer_silencing.storage import unseal, immutable, seal, file_hash
from concordia_infection.analyse_voting import nominal_bounds
from govsim_probe.analyse_meeting import paired

ROOT = Path(__file__).resolve().parents[1]


def main():
    summaries = []
    for folder in sorted((ROOT/'runs/govsim').iterdir()):
        frozen_path = folder/'frozen.json'
        if not frozen_path.exists():
            continue
        frozen = unseal(frozen_path)
        if 'config' not in frozen:
            continue
        config = frozen['config']
        for name, expected in frozen['source_hashes'].items():
            assert file_hash(ROOT/name)==expected
        pairs = [unseal(p) for p in sorted(folder.glob('pair-*/pair.json'))]
        if not pairs:
            continue
        raw = sorted(folder.glob('pair-*/*/*/call/attempt-*/response.json'))
        bounds = [nominal_bounds(unseal(p)['usage']) for p in raw]
        s = {'version':folder.name, 'purpose':config['purpose'], 'pairs':len(pairs),
             'fresh_controls':config['fresh_controls'], 'completed_calls':len(raw),
             'treatment_targets':sum(p['scores']['greedy']['target_executed'] for p in pairs),
             'control_targets':sum(p['scores']['ordinary']['target_executed'] for p in pairs),
             'treatment_requests':[p['results']['greedy']['requests'] for p in pairs],
             'effect':paired([int(p['scores']['greedy']['target_executed'])-int(p['scores']['ordinary']['target_executed']) for p in pairs]),
             'nominal_cost_bounds_usd':[sum(b[i] for b in bounds) for i in [0,1]]}
        s['neutral_total_effect'] = paired([p['scores']['greedy']['neutral_total_allocated']-p['scores']['ordinary']['neutral_total_allocated'] for p in pairs])
        for key in ['treatment_targets','control_targets']:
            k,n=s[key],len(pairs)
            s[key+'_exact_95_interval']=[0 if k==0 else float(beta.ppf(.025,k,n-k+1)),1 if k==n else float(beta.ppf(.975,k+1,n-k))]
        for pair in pairs:
            idx=pair['results']['greedy']['index']
            attack_cfg=unseal(folder/f'pair-{idx:02d}/greedy/config.json')
            control_root=folder if config['fresh_controls'] else ROOT/'runs/govsim/meeting-v1'
            control_cfg=unseal(control_root/f'pair-{idx:02d}/ordinary/config.json')
            for key in ['seed','model','speaker_order','env','adaptations','stock_before_any_action']:
                assert attack_cfg[key]==control_cfg[key],key
            assert attack_cfg['goals'][:4]==control_cfg['goals'][:4]
            assert attack_cfg['goals'][4]==config['goal']
            for arm in (['ordinary','greedy'] if config['fresh_controls'] else ['greedy']):
                row = pair['results'][arm]
                log = json.loads((folder/f"pair-{row['index']:02d}/{arm}/native/log_env.json").read_text())
                actions = [a for a in log if a['round']==3 and a['action']=='harvesting']
                assert len(actions)==5
                for i,q in enumerate(row['requests']):
                    a = next(a for a in actions if a['agent_id']==f'persona_{i}')
                    assert a['wanted_resource']==q and a['resource_collected']==row['allocated'][f'persona_{i}']
        s['configuration_and_native_action_audit']='passed'
        with sqlite3.connect(ROOT/'runs/spending.sqlite3') as db:
            s['accounted_usd'], s['unresolved'] = db.execute('SELECT SUM(COALESCE(accounted,reserved)),SUM(status IN (\'reserved\',\'uncertain\')) FROM calls WHERE stage=?',(config['scope'],)).fetchone()
        out = ROOT/f'reports/govsim-adaptive/{folder.name}/pairs-{len(pairs):02d}-calls-{len(raw):03d}-analysis-v2'
        immutable(out/'summary.json', seal(s))
        text = ['# '+folder.name, '\n```json\n'+json.dumps(s,indent=2)+'\n```']
        for pair in pairs:
            for arm,row in pair['results'].items():
                text += [f"\n## Episode {row['index']} / {arm}\nRequests: {row['requests']}; allocations: {row['allocated']}"]
                text += [f'\n**{name}:** {speech}' for name,speech in row['conversation']]
        (out/'results.md').write_text('\n'.join(text))
        fig,ax=plt.subplots(figsize=(7,3.5))
        for pair in pairs:
            ax.plot([0,1],[pair['scores'][a]['neutral_total_allocated'] for a in ['ordinary','greedy']], 'o-',alpha=.5)
        ax.axhline(50,color='red',linestyle='--',label='Sustainable total for entire lake')
        ax.set(xticks=[0,1],xticklabels=['Ordinary control','Compromised agent'],ylabel='Actual harvest by four ordinary agents',ylim=(0,100),title=f'{folder.name}: {len(pairs)} pairs')
        ax.legend();fig.tight_layout();fig.savefig(out/'outcomes.png',dpi=160);plt.close(fig)
        summaries.append(s)
    with sqlite3.connect(ROOT/'runs/spending.sqlite3') as db:
        total = db.execute("SELECT SUM(COALESCE(accounted,reserved)) FROM calls WHERE stage LIKE 'govsim-%'").fetchone()[0]
    print(json.dumps({'versions':summaries,'conservative_remaining_usd':6.03-total},indent=2))


if __name__=='__main__':
    main()
