import asyncio

import pytest

from peer_silencing.model import SharedLedger
from peer_silencing.storage import IntegrityError
from scripts.complete_attacked_prefix import BoundedLedger, PrefixOnlyClient
from swarm.budget import BudgetExceeded


def test_six_attempt_limit_persists_across_instances(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    ledger = BoundedLedger(path)
    for i in range(6):
        ledger.reserve_call("pilot", str(i), {})
    with pytest.raises(BudgetExceeded):
        BoundedLedger(path).reserve_call("pilot", "seventh", {})


def test_scoped_dollar_limit_counts_uncertain_requests(tmp_path):
    ledger = BoundedLedger(tmp_path / "ledger.sqlite3")
    with pytest.raises(BudgetExceeded):
        ledger.reserve_call("pilot", "large", {"large": "x" * 200000})
    call_id = ledger.reserve_call("pilot", "one", {})
    ledger.uncertain(call_id)
    assert ledger.summary()["stages"]["pilot"]["unresolved_calls"] == 1
    assert isinstance(ledger, SharedLedger)


@pytest.mark.parametrize(
    "scenario,exposure,branch,rnd,agent",
    [
        ("B-01", "attack", "prefix", 5, "Agent_D1"),
        ("A-01", "clean", "prefix", 5, "Agent_D1"),
        ("A-01", "attack", "peer", 6, "Agent_D1"),
        ("A-01", "attack", "prefix", 4, "Agent_D1"),
        ("A-01", "attack", "prefix", 5, "Agent_A"),
    ],
)
def test_no_calls_outside_scope(tmp_path, scenario, exposure, branch, rnd, agent):
    client = PrefixOnlyClient(None)
    with pytest.raises(IntegrityError):
        asyncio.run(
            client.call(
                "s",
                "u",
                tmp_path,
                {
                    "scenario": scenario,
                    "exposure": exposure,
                    "branch": branch,
                    "round": rnd,
                    "agent": agent,
                },
            )
        )
