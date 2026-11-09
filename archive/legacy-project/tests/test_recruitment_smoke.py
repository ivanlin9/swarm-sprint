import asyncio
import json
from dataclasses import replace

import pytest

from swarm.client import validate
from swarm.recruitment_smoke import (
    BID_VALUES,
    CONDITIONS,
    CONTRACTS,
    NAMES,
    PROMOTER,
    RULES,
    SEED,
    Fixture,
    audit_requests,
    episode,
    metrics,
    prompt,
    run_smoke,
    schema,
)
from swarm.settings import Settings


def test_neutral_prompt_isolation_and_unprimed_schema():
    f = Fixture()
    for name in NAMES:
        a = prompt(f, name, "ordinary", "discussion", 1, [], [])
        b = prompt(f, name, "one_promoter", "discussion", 1, [], [])
        assert a[1] == b[1]
        assert a[0] == RULES
        assert b[0] == (RULES + PROMOTER if name == f.opener else RULES)
    assert set(schema("discussion")["properties"]) == {"message"}
    assert set(schema("bid")["properties"]) == {"bid"}
    for word in ("collud", "cartel", "agreement", "independent bidding", "forbid", "rotate"):
        assert word not in RULES.lower()
    for bid in BID_VALUES:
        validate({"bid": bid}, schema("bid"))
    for bid in ("9", "51", 40, "40.0"):
        with pytest.raises((ValueError, TypeError)):
            validate({"bid": bid}, schema("bid"))


def test_equal_competitors_and_reproducible_nonrotating_ties():
    f = Fixture()
    assert f.priority == Fixture().priority
    assert f.priority != Fixture(SEED + 1).priority
    for i in range(1, CONTRACTS + 1):
        assert set(f.priority[i - 1]) == set(NAMES)
        for name in NAMES:
            result = f.settle({n: "11" if n == name else "50" for n in NAMES}, i)
            assert result["winner"] == name
            assert sum(result["profits"].values()) == result["payment"] - 10 == 1
    with pytest.raises(ValueError):
        f.settle(dict.fromkeys(NAMES, "9"), 1)
    with pytest.raises(ValueError):
        f.settle({"A": "40"}, 1)


def test_numeric_metrics_never_call_high_prices_collusion():
    f = Fixture()
    high = [f.settle(dict.fromkeys(NAMES, "50"), i) for i in range(1, 9)]
    m = metrics(f, high)
    assert m["total_payment"] == 400
    assert m["semantic_collusion_status"].startswith("pending")
    for outcome, dev in zip(high, m["profitable_unilateral_deviations"], strict=True):
        for name in NAMES:
            safe = dev["agents"][name]["strict_undercut_guaranteed_gain"]
            assert safe == (
                None
                if name == outcome["winner"]
                else {"alternative_bid": "49", "profit_gain": 39, "alternative_profit": 39}
            )
    low = [f.settle(dict.fromkeys(NAMES, "10"), i) for i in range(1, 9)]
    assert all(
        d["ex_post_best_with_fixed_hidden_ties"] is None
        for r in metrics(f, low)["profitable_unilateral_deviations"]
        for d in r["agents"].values()
    )
    high[0]["payment"] = 12
    with pytest.raises(ValueError, match="settlement"):
        metrics(f, high)
    with pytest.raises(ValueError, match="Incomplete"):
        metrics(f, [])


class RecordingMock:
    """Offline harness-only data. No network, no model, no scientific evidence."""

    stopped = False

    def __init__(self, fail=False):
        self.contexts = []
        self.fail = fail

    async def call(self, system, user, out_schema, path, label):
        context = json.loads(user)
        self.contexts.append(context)
        if self.fail:
            raise ValueError("Deliberate offline failure")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.with_suffix(".request.json").write_text(
            json.dumps(
                {
                    "input": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "text": {"format": {"schema": out_schema}},
                    "model": "offline-mock",
                }
            )
        )
        return (
            {"message": "Offline harness check, not evidence."}
            if context["phase"] == "discussion"
            else {"bid": "11"}
        )


def test_full_pair_orchestration_and_actual_request_audit(tmp_path):
    client = RecordingMock()
    for condition in CONDITIONS:
        result = asyncio.run(episode(client, tmp_path, condition))
        assert result["status"] == "complete"
        assert result["metrics"]["total_payment"] == 88
    assert len(client.contexts) == 160
    assert audit_requests(tmp_path, Fixture())["paired_ordinary_calls_checked"] == 70
    for c in client.contexts:
        if c["phase"] == "discussion":
            assert not c["previous_outcomes"]
            expected = 8 if c["index"] == 2 else (0 if c["you"] == c["opener"] else 1)
            assert len(c["public_messages"]) == expected
        else:
            assert len(c["previous_outcomes"]) == c["index"] - 1
            assert len(c["public_messages"]) == 16
            assert all(o["contract"] < c["index"] for o in c["previous_outcomes"])
    path = tmp_path / f"{SEED}-one_promoter/calls/bid-1-{Fixture().targets[0]}.request.json"
    request = json.loads(path.read_text())
    request["input"][0]["content"] += " Join the agreement."
    path.write_text(json.dumps(request))
    with pytest.raises(AssertionError):
        audit_requests(tmp_path, Fixture())


def test_failed_episode_is_incomplete_not_a_negative(tmp_path):
    client = RecordingMock(fail=True)
    with pytest.raises(RuntimeError, match="Batch failed"):
        asyncio.run(episode(client, tmp_path, "ordinary"))
    result = json.loads((tmp_path / f"{SEED}-ordinary/result.json").read_text())
    assert result["status"] == "incomplete"
    assert client.stopped


def test_fixed_batch_cannot_be_silently_repeated(tmp_path):
    from swarm.recruitment_smoke import VERSION

    folder = tmp_path / "paid/prior-attempt"
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps({"protocol_version": VERSION}))
    settings = replace(Settings(), runs=tmp_path, max_output=1024)
    with pytest.raises(ValueError, match="already attempted"):
        asyncio.run(run_smoke(RecordingMock(), settings))
