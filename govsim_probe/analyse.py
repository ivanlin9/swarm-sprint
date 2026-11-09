"""Offline summary of the entry feasibility probe; no API access."""
import json
import sqlite3
import statistics
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from peer_silencing.storage import immutable, seal, unseal, file_hash
from concordia_infection.analyse_voting import nominal_bounds

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'runs/govsim/native-entry-probe-v1'
OUT = ROOT / 'reports/govsim-entry-probe'


def main():
    results = unseal(RUN / 'results.json')
    by_arm = {a: [r for r in results if r['arm'] == a] for a in ['ordinary', 'greedy']}
    summary = {'kind': 'native entry feasibility; scripted locals; NOT contagion', 'arms': {}}
    for arm, rows in by_arm.items():
        values = [r['newcomer_requested'] for r in rows]
        summary['arms'][arm] = {
            'requests': values, 'mean_requested': statistics.mean(values),
            'sd_requested': statistics.stdev(values),
            'terminated': sum(r['terminated_before_next_harvest'] for r in rows),
            'n': len(rows)}
    raw_paths = sorted(RUN.glob('seed-*/*/call/attempt-*/response.json'))
    bounds = [nominal_bounds(unseal(p)['usage']) for p in raw_paths]
    with sqlite3.connect(ROOT / 'runs/spending.sqlite3') as db:
        db.row_factory = sqlite3.Row
        ledger = [dict(r) for r in db.execute('SELECT * FROM calls WHERE stage=?', ('govsim-entry-20261108',))]
    accounted = sum(r['accounted'] if r['accounted'] is not None else r['reserved'] for r in ledger)
    summary.update({'completed_requests': len(raw_paths), 'ledger_calls': len(ledger),
                    'nominal_cost_bounds_usd': [sum(b[i] for b in bounds) for i in [0, 1]],
                    'conservative_accounted_usd': accounted,
                    'conservative_remaining_from_6_03_usd': 6.03 - accounted,
                    'decision': 'Do not scale native newcomer sequence for contagion on this evidence.'})
    immutable(OUT / 'summary.json', seal(summary))
    immutable(OUT / 'ledger.json', seal(ledger))
    transcripts = []
    for p in raw_paths:
        raw = unseal(p)
        transcript = '\n'.join(part['text'] for item in raw['output'] if item['type'] == 'message'
                               for part in item['content'] if part['type'] == 'output_text')
        transcripts.append(f'## {p.relative_to(RUN).parts[0]} / {p.relative_to(RUN).parts[1]}\n\n{transcript}\n')
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'transcripts.md').write_text('# Native newcomer action responses\n\n' + '\n'.join(transcripts))
    fig, axes = plt.subplots(1, 2, figsize=(8, 3.5))
    axes[0].bar(['Ordinary', 'Greedy'], [summary['arms'][a]['mean_requested'] for a in by_arm], color=['#327fa8', '#c45348'])
    axes[0].set(ylabel='Requested harvest (tons)', ylim=(0, 110), title='Incoming LLM agent: 3 calls per arm')
    axes[1].bar(['Ordinary', 'Greedy'], [summary['arms'][a]['terminated'] for a in by_arm], color=['#327fa8', '#c45348'])
    axes[1].set(ylabel='Runs ending before next harvest', ylim=(0, 3.5), title='Native resource termination')
    fig.suptitle('Feasibility only: four scripted locals, not a swarm influence test', fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT / 'feasibility.png', dpi=160)
    plt.close(fig)
    immutable(OUT / 'raw_manifest.json', seal({str(p.relative_to(ROOT)): file_hash(p)
              for p in sorted(RUN.rglob('*')) if p.is_file() and p.name != '.run.lock'}))
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
