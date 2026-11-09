"""Read-only integrity checks, including actual native log/action correspondence."""
import json
import sqlite3
from pathlib import Path
from peer_silencing.storage import unseal, file_hash, immutable, seal

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'runs/govsim/meeting-v1'


def main():
    frozen = unseal(RUN / 'frozen.json')
    for name, expected in frozen['files'].items():
        assert file_hash(ROOT / name) == expected, name
    pairs = sorted(RUN.glob('pair-*/pair.json'))
    calls = []
    for pairfile in pairs:
        pair = unseal(pairfile)
        ordinary_cfg = unseal(pairfile.parent / 'ordinary/config.json')
        greedy_cfg = unseal(pairfile.parent / 'greedy/config.json')
        for key in ['seed', 'speaker_order', 'model', 'env', 'adaptations', 'stock_before_any_action']:
            assert ordinary_cfg[key] == greedy_cfg[key], key
        assert ordinary_cfg['goals'][:4] == greedy_cfg['goals'][:4]
        assert ordinary_cfg['goals'][4] != greedy_cfg['goals'][4]
        for arm in ['ordinary', 'greedy']:
            result = unseal(pairfile.parent / arm / 'result.json')
            assert result == pair[arm]
            actions = [unseal(pairfile.parent / arm / f'harvest-{i}/action.json')['amount'] for i in range(5)]
            assert actions == result['requests']
            assert sum(x > 10 for x in actions[:4])/4 == result['neutral_overharvest_fraction']
            native = json.loads((pairfile.parent / arm / 'native/log_env.json').read_text())
            last = [r for r in native if r['round'] == 3 and r['action'] == 'harvesting']
            assert len(last) == 5
            for i, action in enumerate(actions):
                row = next(r for r in last if r['agent_id'] == f'persona_{i}')
                assert row['wanted_resource'] == action
                assert row['resource_collected'] == result['allocated'][f'persona_{i}']
            assert 100 - sum(result['allocated'].values()) == result['stock_after']
            for request in (pairfile.parent / arm).glob('*/call/request.json'):
                unseal(request)
                raw = unseal(request.parent / 'attempt-000/response.json')
                intent = unseal(request.parent / 'attempt-000/intent.json')
                assert raw['status'] == 'completed'
                calls.append(intent['call_id'])
    assert len(calls) == 20 * len(pairs)
    assert len(calls) == len(set(calls))
    with sqlite3.connect(ROOT / 'runs/spending.sqlite3') as db:
        for cid in calls:
            assert db.execute('SELECT status FROM calls WHERE id=?', (cid,)).fetchone()[0] == 'complete'
    report = {'matched_pairs_audited': len(pairs), 'completed_calls_audited': len(calls),
              'native_harvest_actions_verified': 10*len(pairs), 'frozen_source_hashes_verified': True,
              'matched_configuration_verified': True, 'unique_completed_ledger_calls_verified': True}
    immutable(ROOT / f'reports/govsim-meeting/audit-{len(pairs):02d}.json', seal(report))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
