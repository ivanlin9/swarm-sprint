import json
import pytest
from govsim_probe import swarm25_replicates as r
from govsim_probe import swarm25_highdose as h
from govsim_probe import large_swarm as s
from swarm.budget import BudgetExceeded

def test_design():
    cfg=json.loads(r.POLICY.read_text());jobs=r.jobs(cfg)
    assert len(jobs)==len(set(jobs))==18
    with h.context():
        for b in cfg['blocks']:
            src,rec=s.roles(b)
            assert len(rec)==15 and len(src)==10
            for i in rec:assert len({s.system(i,c,b) for c in cfg['counts']})==1
            assert sum(len(ids) for _,ids in s.phase_schedule(b))+25==75
            for c in cfg['counts']:assert sum(bool(s.goal(i,c,b)) for i in range(25))==c

def test_new_authorization_limit(tmp_path):
    ledger=r.Ledger();ledger.path=tmp_path/'test.sqlite3'
    cfg=ledger.config.copy();cfg['paid_enabled']=True
    ledger.config=cfg;ledger.policy_path=tmp_path/'policy.json';ledger.policy_path.write_text(json.dumps(cfg))
    with ledger.connect() as db:
        db.execute('CREATE TABLE calls(id TEXT,stage TEXT,label TEXT,status TEXT,reserved REAL,accounted REAL)')
        db.execute('INSERT INTO calls VALUES (?,?,?,?,?,?)',('old','govsim-old','old','complete',44.630586,44.630586))
    assert ledger.reserve_request('test',{'max_output_tokens':1600,'input':[]})
    with ledger.connect() as db:
        db.execute('INSERT INTO calls VALUES (?,?,?,?,?,?)',('full',cfg['scope'],'full','complete',24.999,24.999))
    with pytest.raises(BudgetExceeded):ledger.reserve_request('blocked',{'max_output_tokens':1600,'input':[]})
