import json
import pytest
from govsim_probe import swarm25_extension as e
from peer_silencing.storage import unseal,file_hash
from swarm.budget import BudgetExceeded

def test_protocol_unchanged_and_fresh_blocks():
    original=unseal(e.ORIGINAL_RUN/'protocol.json')
    for name,expected in original['source_hashes'].items():assert file_hash(e.r.s.ROOT/name)==expected
    cfg=json.loads(e.POLICY.read_text());jobs=e.r.jobs(cfg)
    assert len(jobs)==len(set(jobs))==12
    assert {b for b,c in jobs}=={4,5}
    with e.r.h.context():
        for b in [4,5]:
            src,rec=e.r.s.roles(b)
            assert len(src)==10 and len(rec)==15
            for i in rec:assert len({e.r.s.system(i,c,b) for c in cfg['counts']})==1

def test_extension_allowance(tmp_path, monkeypatch):
    # Budget tests must not depend on retained stop markers from real API runs.
    monkeypatch.setattr(e,'RUN',tmp_path/'isolated-run')
    l=e.Ledger();l.path=tmp_path/'ledger.sqlite3';l.config['paid_enabled']=True
    l.policy_path=tmp_path/'policy.json';l.policy_path.write_text(json.dumps(l.config))
    with l.connect() as db:
        db.execute('CREATE TABLE calls(id TEXT,stage TEXT,label TEXT,status TEXT,reserved REAL,accounted REAL)')
        db.execute('INSERT INTO calls VALUES (?,?,?,?,?,?)',('old','govsim-old','old','complete',63.190039,63.190039))
    assert l.reserve_request('first',{'max_output_tokens':1600,'input':[]})
    with l.connect() as db:db.execute('INSERT INTO calls VALUES (?,?,?,?,?,?)',('full',l.config['scope'],'full','complete',14.999,14.999))
    with pytest.raises(BudgetExceeded):l.reserve_request('blocked',{'max_output_tokens':1600,'input':[]})
