import pytest
from govsim_probe import swarm25_extension_retry as r
from peer_silencing.storage import unseal

def test_exact_allowlist_only():
    assert len(r.ALLOWED)==3
    for rel in r.ALLOWED:
        d=r.RUN/rel;req=unseal(d/'request.json')
        assert r.mapped_directory(d,req)==d/'authorized-retry-001'
        with pytest.raises(AssertionError):r.mapped_directory(d,{'different':'request'})
    d=r.RUN/'block-04/r0/opening/actor-00/call'
    assert r.mapped_directory(d,{})==d

def test_budget_preserves_uncertain_charges():
    ledger=r.Ledger()
    assert ledger.config['additional_cap_usd']==15
    assert ledger.config['max_calls']==903
    with ledger.connect() as db:
        count,cost=db.execute('SELECT COUNT(*),SUM(reserved) FROM calls WHERE stage=? AND status=?',(ledger.config['scope'],'uncertain')).fetchone()
    assert count==3 and cost>0
