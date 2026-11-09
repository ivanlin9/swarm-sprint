"""Offline standard-library audit: no network, API key or third-party imports."""
import hashlib
import json
from pathlib import Path
import statistics

ROOT=Path(__file__).resolve().parents[1]

def read_sealed(path):
    obj=json.loads(path.read_text())
    canonical=json.dumps(obj['data'],sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
    assert hashlib.sha256(canonical).hexdigest()==obj['sha256'],str(path)
    return obj['data']

def main():
    index=json.loads((ROOT/'results_index.json').read_text())['primary_study']
    cells={};audited=set()
    for folder in index['raw_directories']:
        root=ROOT/folder
        for p in root.glob('block-*/*/outcome.json'):
            row=read_sealed(p);key=(row['block'],row['recruiter_count'])
            assert key not in cells
            assert len(row['ordinary_allocated'])==len(row['recipient_ids'])==15
            assert statistics.mean(row['ordinary_allocated'])==row['ordinary_mean_allocated']
            cfg=read_sealed(p.parent/'config.json')
            assert set(cfg['sources']).isdisjoint(row['recipient_ids'])
            for actor,amount in zip(row['recipient_ids'],row['ordinary_requested']):
                assert read_sealed(p.parent/f'action/actor-{actor:02d}/action.json')['amount']==amount
            cells[key]=row
        for p in root.rglob('audit-b*-r*.json'):
            audit=read_sealed(p)
            if audit['offline_replay_passed']:audited.add((audit['block'],audit['count']))
    expected={(b,c) for b in range(1,6) for c in index['recruiter_counts']}
    assert set(cells)==expected and expected<=audited
    for j,c in enumerate(index['recruiter_counts']):
        total=statistics.mean(sum(cells[b,c]['ordinary_allocated']) for b in range(1,6))
        assert abs(total-index['mean_total_tons'][j])<1e-9
    for p in (ROOT/'configs').glob('*.json'):
        cfg=json.loads(p.read_text())
        assert cfg.get('paid_enabled') is not True, f'Paid execution enabled: {p}'
    for key in ['summary','total_plot','average_plot']:assert (ROOT/index[key]).is_file()
    print('PASS: 30 sealed outcomes, action consistency, source exclusions, replay records, result index and disabled paid policies.')

if __name__=='__main__':main()
