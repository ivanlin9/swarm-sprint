"""Offline episode-level descriptive and paired analysis, with full transcripts."""
import itertools
import json
import sqlite3
import statistics
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from peer_silencing.storage import unseal, immutable, seal, file_hash
from concordia_infection.analyse_voting import nominal_bounds

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'runs/govsim/meeting-v1'


def paired(values):
    mean = statistics.mean(values)
    null = [abs(sum(v*s for v, s in zip(values, signs))) for signs in itertools.product([-1, 1], repeat=len(values))]
    return {'differences': values, 'mean_difference': mean,
            'sd_paired_difference': statistics.stdev(values) if len(values) > 1 else None,
            'exact_two_sided_sign_flip_p': sum(x >= abs(sum(values)) - 1e-12 for x in null) / len(null),
            'positive_pairs': sum(x > 0 for x in values),
            'negative_pairs': sum(x < 0 for x in values), 'ties': sum(x == 0 for x in values)}


def main():
    pairs = [unseal(p) for p in sorted(RUN.glob('pair-*/pair.json'))]
    if not pairs:
        raise SystemExit('No complete matched pairs yet')
    paths = sorted(RUN.glob('pair-*/*/*/call/attempt-*/response.json'))
    out = ROOT / f'reports/govsim-meeting/pairs-{len(pairs):02d}-calls-{len(paths):03d}'
    summary = {'complete_pairs': len(pairs), 'completed_calls': len(paths), 'arms': {}, 'effects': {}}
    for arm in ['ordinary', 'greedy']:
        summary['arms'][arm] = {}
        for field in ['neutral_overharvest_fraction', 'neutral_mean_request', 'neutral_excess_tons']:
            values = [p[arm][field] for p in pairs]
            summary['arms'][arm][field] = {'values': values, 'mean': statistics.mean(values),
                                         'sd_across_episodes': statistics.stdev(values) if len(values)>1 else None}
    for field in summary['arms']['ordinary']:
        summary['effects'][field] = paired([p['greedy'][field]-p['ordinary'][field] for p in pairs])
    effect = summary['effects']['neutral_overharvest_fraction']
    summary['continuation_gate'] = len(pairs) == 10 and effect['positive_pairs'] >= 3 and effect['mean_difference'] >= .15
    with sqlite3.connect(ROOT / 'runs/spending.sqlite3') as db:
        db.row_factory = sqlite3.Row
        ledger = [dict(r) for r in db.execute('SELECT * FROM calls WHERE stage=?', ('govsim-meeting-20261108',))]
        govsim_total = db.execute("SELECT SUM(COALESCE(accounted,reserved)) FROM calls WHERE stage LIKE 'govsim-%'").fetchone()[0]
    costs = [nominal_bounds(unseal(p)['usage']) for p in paths]
    summary['nominal_cost_bounds_usd'] = [sum(c[i] for c in costs) for i in [0,1]]
    summary['conservative_accounted_usd'] = sum(r['accounted'] if r['accounted'] is not None else r['reserved'] for r in ledger)
    summary['conservative_remaining_usd'] = 6.03-govsim_total
    summary['unresolved_calls'] = sum(r['status'] in ['reserved','uncertain'] for r in ledger)
    immutable(out / 'summary.json', seal(summary))
    immutable(out / 'ledger.json', seal(ledger))
    lines = ['# GovSim pre-harvest meeting: complete paired episodes\n',
             'Adapted single-meeting pilot. Ordinary-agent actions, not verbal assent, are the outcome.\n']
    for p in pairs:
        for arm in ['ordinary', 'greedy']:
            row = p[arm]
            lines += [f"## Pair {row['index']} — {arm}\n", f"Harvest requests [John, Kate, Jack, Emma, Luke]: {row['requests']}\n",
                      f"Actual allocations: {row['allocated']}; stock left: {row['stock_after']}.\n"]
            for name, text in row['conversation']:
                lines += [f'### {name}\n', text+'\n']
    (out / 'transcripts.md').write_text('\n'.join(lines))
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for i, p in enumerate(pairs):
        axes[0].plot([0,1], [p[a]['neutral_overharvest_fraction'] for a in ['ordinary','greedy']], 'o-', alpha=.45)
        axes[1].plot([i-.12, i+.12], [p[a]['neutral_mean_request'] for a in ['ordinary','greedy']], 'o-', alpha=.65)
    axes[0].set(xticks=[0,1], xticklabels=['Ordinary newcomer','Greedy newcomer'], ylabel='Ordinary-agent overharvest fraction', ylim=(-.05,1.05), title='Each line is one matched pair')
    axes[1].axhline(10, color='gray', linestyle='--', label='Equal sustainable share')
    axes[1].set(xlabel='Pair index (ordinary left; greedy right)', ylabel='Mean ordinary-agent harvest request', title='Behaviour, excluding newcomer')
    axes[1].legend()
    fig.suptitle(f'Adapted GovSim meeting pilot — {len(pairs)} pairs, one decision per agent')
    fig.tight_layout()
    fig.savefig(out / 'outcomes.png', dpi=160)
    plt.close(fig)
    immutable(out / 'manifest.json', seal({str(p.relative_to(ROOT)): file_hash(p) for p in sorted(RUN.rglob('*')) if p.is_file() and p.name != '.run.lock'}))
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
