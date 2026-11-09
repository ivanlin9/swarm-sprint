from datetime import datetime, timezone
import pytest
from govsim_probe import bridge as b
from govsim_probe import bargaining_corrected as corrected
from govsim_probe.test_breadth import FakeClient
from peer_silencing.storage import unseal
from oasis_probe.client import Halt

@pytest.mark.parametrize('condition',b.CONDITIONS)
def test_bridge_native(tmp_path,condition):
    original=corrected.GOALS
    client=FakeClient();result=b.execute(20,condition,client,root=tmp_path)
    assert corrected.GOALS is original
    assert len(client.requests)==11 and result['ordinary_allocated']==[10]*4
    cfg=unseal(tmp_path/'block-20'/condition/'config.json')
    assert cfg['goals'][:4]==[b.b.components('fishing')[5]]*4
    if condition!='baseline':assert cfg['goals'][4]==b.GOALS[condition]
    for request in client.requests[6:10]:
        assert all(goal not in message['content'] for goal in b.GOALS.values() for message in request['input'])

def test_deadline_blocks_before_transport(tmp_path):
    class Forbidden:
        replay=False
        def call(self,*args):raise AssertionError('Must not dispatch')
    client=b.BoundedClient(Forbidden(),{'deadline_utc':'2026-11-09T03:00:00+00:00'},
        now=lambda:datetime(2026,11,9,3,tzinfo=timezone.utc))
    with pytest.raises(Halt,match='deadline'):client.call(tmp_path,{})
