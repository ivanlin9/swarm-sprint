from govsim_probe import swarm25_followup as f
from govsim_probe import swarm25 as t
from govsim_probe import large_swarm as s
from peer_silencing.storage import unseal, file_hash

def test_frozen_sources_and_ordinary_prompts():
    protocol=unseal(t.RUN/'protocol.json')
    for name,expected in protocol['source_hashes'].items():assert file_hash(s.ROOT/name)==expected
    baseline=unseal(t.RUN/'block-00/r0/config.json')
    with t.context():
        for count in [1,3]:
            for i in baseline['recipients']:assert s.system(i,count,0)==baseline['systems'][i]
            assert sum(bool(s.goal(i,count,0)) for i in range(25))==count
            assert s.phase_schedule(0)==baseline['schedule']

def test_distinct_paths():
    assert f.RUN!=t.RUN and f.POLICY!=t.POLICY
