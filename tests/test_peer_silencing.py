"""All new-pipeline tests are offline; network transports are blocked by default."""

import asyncio
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest
from openai import APITimeoutError, RateLimitError

from peer_silencing import __main__ as cli
from peer_silencing.analysis import calibration, cell, evaluate, paired_summary
from peer_silencing.engine import execute, segment
from peer_silencing.model import (
    OfflineClient,
    PaidClient,
    SharedLedger,
    StopRun,
    TurnFailure,
    ledger_snapshot,
    parse_response,
    request_payload,
)
from peer_silencing.protocol import (
    FOCAL,
    MAIN,
    MODEL,
    action,
    history,
    load_manifest,
    make_manifest,
    native,
    prepare,
    prompts_for,
    scenarios,
    scripted,
    selected_main,
    validate_output,
)
from peer_silencing.storage import IntegrityError, digest, immutable, seal, unseal
from swarm.budget import BudgetExceeded


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Tests must not create real API transports")

    monkeypatch.setattr("peer_silencing.model.AsyncOpenAI", blocked)
    monkeypatch.setattr(httpx.Client, "send", blocked)
    monkeypatch.setattr(httpx.AsyncClient, "send", blocked)


def valid(verdict="Buy", message="Public fixture"):
    return {"thought": "PRIVATE_SENTINEL", "verdict": verdict, "message": message}


def response(output=None, status="completed"):
    return {
        "id": "resp_fake",
        "status": status,
        "service_tier": "default",
        "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
            "input_tokens_details": {"cached_tokens": 10, "cache_write_tokens": 0},
        },
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": json.dumps(output or valid())}],
            }
        ],
    }


class FakeTransport:
    def __init__(self, *items):
        self.items = list(items)
        self.payloads = []
        self.responses = self

    async def create(self, **kwargs):
        self.payloads.append(kwargs)
        item = self.items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return SimpleNamespace(model_dump=lambda **kw: item)

    async def close(self):
        pass


def paid(tmp_path, *items):
    ledger = SharedLedger(tmp_path / "ledger.sqlite3")
    transport = FakeTransport(*items)
    client = PaidClient(
        "sk-TEST-SECRET", ledger, "pilot", transport=transport, cutoff="2099-01-01T00:00:00+00:00"
    )
    return client, ledger, transport


def call(client, tmp_path):
    return asyncio.run(client.call("system", "user", tmp_path / "call", {"category": "peer"}))


@pytest.mark.parametrize("stage,n", [("smoke", 278), ("main", 1112)])
def test_manifest_selection_counts_and_paired_schedules(stage, n):
    m = make_manifest(stage, "offline")
    assert selected_main() == MAIN
    assert m["nominal_calls"] == sum(m["nominal_calls_by_category"].values()) == n
    assert len(m["scenario_ids"]) == n // 139
    for schedule in m["schedules"].values():
        assert all(set(order) == {*FOCAL, "source"} for order in schedule["prefix"].values())
        assert all(set(order) == set(FOCAL) for order in schedule["continuation"].values())
    assert MODEL["reasoning"] == {"effort": "low"}


@pytest.mark.parametrize("sid", ["A-01", "B-01"])
@pytest.mark.parametrize("agent,rnd", [("Agent_D1", 1), ("Agent_D7", 5), ("Agent_A", 2)])
def test_native_prompt_parity_and_no_extra_dataset_fields(monkeypatch, sid, agent, rnd):
    _, agents = native()
    captured = []
    monkeypatch.setattr(
        agents,
        "call_json",
        lambda backend, system, user: captured.append((system, user)) or valid(),
    )
    scenario = scenarios()[sid]
    instance = (
        agents.ScriptedAttackerAgent(agent, {}, 3)
        if agent == "Agent_A"
        else agents.DefenderAgent(agent, {})
    )
    instance.respond(rnd, "history sentinel", scenario)
    assert prompts_for(agent, rnd, scenario, "history sentinel") == captured[0]
    if agent != "Agent_A":
        modified = {
            **scenario,
            "type": "SECRET_LABEL",
            "headlines": ["SECRET_HEADLINE"],
            "attacker_poison_message": "SECRET_ATTACK",
            "rationale": "SECRET_REASON",
        }
        assert prompts_for(agent, rnd, modified, "history sentinel") == captured[0]


@pytest.mark.parametrize("sid", ["A-01", "B-01"])
@pytest.mark.parametrize("rnd", [3, 4, 5])
def test_native_scripted_parity_no_model(monkeypatch, sid, rnd):
    _, agents = native()

    def forbidden(*args, **kwargs):
        raise AssertionError("Scripted turn attempted API")

    monkeypatch.setattr(agents, "call_json", forbidden)
    scenario = scenarios()[sid]
    expected = agents.ScriptedAttackerAgent("Agent_A", {}, 3).respond(rnd, "", scenario)
    assert scripted(rnd, scenario) == expected


def test_history_keeps_old_peers_and_source_but_not_new_peers():
    prefix = [
        {"sender": "Agent_A", "message": "old attack"},
        {"sender": "Agent_D2", "message": "old peer"},
    ]
    new = [
        {"sender": "System", "message": "marker"},
        {"sender": "Agent_D1", "message": "own"},
        {"sender": "Agent_D2", "message": "new peer"},
    ]
    independent = history(prefix, new, "Agent_D1", "independent")
    assert all(text in independent for text in ("old attack", "old peer", "own", "marker"))
    assert "new peer" not in independent
    assert "new peer" in history(prefix, new, "Agent_D1", "peer")


@pytest.mark.parametrize(
    "value",
    [
        {},
        valid("not buy"),
        valid("BUY"),
        {**valid(), "extra": 1},
        valid(message=" "),
        {**valid(), "message": {"text": "x"}},
    ],
)
def test_invalid_outputs_never_hold(value):
    with pytest.raises(ValueError):
        validate_output(value)
    with pytest.raises(TurnFailure):
        parse_response(response(output=value) if value else response(output={"x": 1}))


@pytest.mark.parametrize(
    "verdict,expected",
    [
        ("Buy", "buy"),
        ("Strong Buy", "buy"),
        ("Hold", "hold"),
        ("Sell", "sell"),
        ("Strong Sell", "sell"),
    ],
)
def test_exact_actions(verdict, expected):
    assert action(verdict) == expected
    with pytest.raises(ValueError):
        action("not " + verdict)


def test_payload_no_hidden_state_or_tools():
    p = request_payload("s", "u")
    assert p["text"]["format"]["strict"] is True
    assert p["store"] is False and p["truncation"] == "disabled"
    assert not {"tools", "previous_response_id", "conversation"} & p.keys()
    assert p["max_output_tokens"] == 2048


def test_end_to_end_smoke_visibility_counts_and_zero_call_resume(tmp_path):
    m = prepare(tmp_path, "smoke", "offline")
    client = OfflineClient()
    asyncio.run(execute(tmp_path, m, client))
    assert client.calls == 278
    for sid in m["scenario_ids"]:
        for exposure in ("attack", "clean"):
            base = tmp_path / "scenarios" / sid / exposure
            prefix = unseal(base / "prefix/checkpoint.json")
            assert len(prefix["events"]) == 35
            assert sum(e["kind"] == "scripted" for e in prefix["events"]) == (
                3 if exposure == "attack" else 0
            )
            for branch in ("peer", "independent"):
                cp = unseal(base / branch / "checkpoint.json")
                assert cp["prefix_hash"] == digest(prefix)
                assert cp["transcript"][: len(prefix["transcript"])] == prefix["transcript"]
                assert len(cp["events"]) == 18
                assert {e["metadata"]["agent"] for e in cp["events"]} == set(FOCAL)
                for event in cp["events"]:
                    rnd, agent = event["metadata"]["round"], event["metadata"]["agent"]
                    req = unseal(base / branch / "calls" / f"r{rnd}-{agent}" / "request.json")
                    prompt = req["payload"]["input"][1]["content"]
                    before = cp["transcript"][
                        : next(
                            i
                            for i, e in enumerate(cp["transcript"])
                            if e["id"] == f"r{rnd}-{agent}"
                        )
                    ]
                    for msg in before:
                        visible = (
                            msg["round"] <= 5
                            or branch == "peer"
                            or msg["sender"] in {agent, "System"}
                        )
                        assert (msg["message"] in prompt) == visible
                    assert "Offline fixture only." not in prompt
    result = evaluate(tmp_path)
    assert result["complete_four_cell_scenarios"] == 2
    assert result["primary"]["mean"] == 0
    assert result["primary"]["exploratory_ci95"] is None
    assert result["calls"]["completed_requests"] == 278
    again = OfflineClient()
    asyncio.run(execute(tmp_path, m, again))
    assert again.calls == 0
    with pytest.raises(IntegrityError):
        calibration(tmp_path, make_manifest("main", "paid"))


def test_interrupt_after_result_before_event_resumes_identically(tmp_path):
    m = prepare(tmp_path, "smoke", "offline")
    scenario = scenarios()["A-01"]

    class Interrupt(OfflineClient):
        async def call(self, *args):
            result = await super().call(*args)
            if self.calls == 3:
                raise StopRun("Simulated interruption")
            return result

    interrupted = tmp_path / "interrupted"
    with pytest.raises(StopRun):
        asyncio.run(segment(interrupted, m, scenario, "attack", "prefix", Interrupt()))
    resumed = OfflineClient()
    cp = asyncio.run(segment(interrupted, m, scenario, "attack", "prefix", resumed))
    assert resumed.calls == 29  # three model outputs already durably saved
    reference = asyncio.run(
        segment(tmp_path / "reference", m, scenario, "attack", "prefix", OfflineClient())
    )
    assert cp == reference


def test_terminal_branch_missing_not_hold_and_not_resampled(tmp_path):
    m = prepare(tmp_path, "smoke", "offline")

    class Failure(OfflineClient):
        async def call(self, system, user, directory, metadata):
            if (
                metadata["scenario"] == "A-01"
                and metadata["exposure"] == "attack"
                and metadata["branch"] == "peer"
            ):
                raise TurnFailure("Truncated fixture")
            return await super().call(system, user, directory, metadata)

    asyncio.run(execute(tmp_path, m, Failure()))
    result = evaluate(tmp_path)
    row = result["rows"][0]
    assert row["D_attack"] is None and row["D_clean"] == 0
    assert "attack/peer" not in row["cells"]
    assert "attack/independent" in row["cells"]
    assert result["primary"]["n_complete"] == 1
    assert result["primary"]["missing_bounds"] == [-0.5, 0.5]
    resumed = OfflineClient()
    asyncio.run(execute(tmp_path, m, resumed))
    assert resumed.calls == 0


def votes_checkpoint(votes, rounds):
    return {
        "events": [
            {"metadata": {"round": rnd, "agent": agent}, "output": valid(vote)}
            for rnd in rounds
            for agent, vote in zip(FOCAL, votes)
        ]
    }


def test_scoring_transitions_and_undefined_recovery():
    prefix = votes_checkpoint(["Buy", "Buy", "Hold", "Sell", "Hold", "Buy"], [5])
    continuation = votes_checkpoint(["Buy", "Hold", "Buy", "Sell", "Hold", "Buy"], [6, 7, 8])
    continuation["prefix_hash"] = digest(prefix)
    c = cell(prefix, continuation, "buy")
    assert c["noncorrect"] == 0.5 and c["hold"] == 2 / 6 and c["opposite"] == 1 / 6
    assert c["transitions"] == {
        "maintained": 2,
        "new_disagreement": 1,
        "recovered": 1,
        "persistent": 2,
    }
    assert c["conditional_recovery"] == 1 / 3
    correct = votes_checkpoint(["Buy"] * 6, [5])
    continuation["prefix_hash"] = digest(correct)
    assert cell(correct, continuation, "buy")["conditional_recovery"] is None
    continuation["events"].pop()
    with pytest.raises(IntegrityError):
        cell(correct, continuation, "buy")


def test_scenario_bootstrap_and_missing_bounds():
    rows = [
        {"scenario": f"{label}-{i}", "effect": v}
        for label in ("A", "B")
        for i, v in enumerate((-0.5, 0.5))
    ]
    summary = paired_summary(rows, "effect", 4)
    assert summary["mean"] == 0 and summary["exploratory_ci95"] == [-0.5, 0.5]
    assert summary == paired_summary(rows, "effect", 4)
    rows[0]["effect"] = None
    missing = paired_summary(rows, "effect", 4, bound=2)
    assert missing["missing_bounds"] == [-0.375, 0.625]
    assert missing["exploratory_ci95"] is None


def test_integrity_conflicts_and_changed_manifest(tmp_path, monkeypatch):
    prepare(tmp_path, "smoke", "offline")
    with pytest.raises(IntegrityError):
        immutable(tmp_path / "manifest.json", seal({"changed": True}))
    monkeypatch.setattr("peer_silencing.protocol.code_fingerprint", lambda: {"changed": "yes"})
    with pytest.raises(IntegrityError):
        load_manifest(tmp_path)
    # A corrupt envelope cannot be consumed as a valid checkpoint.
    immutable(tmp_path / "corrupt.json", {"sha256": "wrong", "data": {}})
    with pytest.raises(IntegrityError):
        unseal(tmp_path / "corrupt.json")


def test_paid_fake_success_accounting_and_resume(tmp_path):
    client, ledger, transport = paid(tmp_path, response())
    assert call(client, tmp_path) == valid()
    assert call(client, tmp_path) == valid()
    assert len(transport.payloads) == 1
    snapshot = ledger_snapshot(ledger.path)
    assert snapshot["calls"] == 1 and snapshot["unresolved"] == 0
    assert snapshot["accounted_usd"] == pytest.approx(0.0011)
    for path in (tmp_path / "call").glob("*.json"):
        assert "sk-TEST-SECRET" not in path.read_text()


def test_timeout_retains_reservation_stops_and_never_retries(tmp_path):
    timeout = APITimeoutError(request=httpx.Request("POST", "https://invalid.example"))
    client, ledger, transport = paid(tmp_path, timeout)
    with pytest.raises(StopRun):
        call(client, tmp_path)
    assert client.stopped and len(transport.payloads) == 1
    assert ledger_snapshot(ledger.path)["unresolved"] == 1
    with pytest.raises(StopRun):
        call(client, tmp_path)
    assert len(transport.payloads) == 1


def test_one_explicit_retry_fresh_reservation_same_input(tmp_path, monkeypatch):
    async def no_sleep(*args):
        pass

    monkeypatch.setattr("peer_silencing.model.asyncio.sleep", no_sleep)
    error = RateLimitError(
        "DO_NOT_LOG_SECRET",
        response=httpx.Response(429, request=httpx.Request("POST", "https://invalid.example")),
        body=None,
    )
    client, ledger, transport = paid(tmp_path, error, response())
    assert call(client, tmp_path) == valid()
    assert len(transport.payloads) == 2 and transport.payloads[0] == transport.payloads[1]
    snapshot = ledger_snapshot(ledger.path)
    assert snapshot["calls"] == 2 and snapshot["unresolved"] == 1
    assert snapshot["accounted_usd"] > 0.0011
    assert "DO_NOT_LOG_SECRET" not in (tmp_path / "call/attempt-0.error.json").read_text()
    ids = [unseal(tmp_path / f"call/attempt-{i}.intent.json")["call_id"] for i in range(2)]
    assert ids[0] != ids[1]


@pytest.mark.parametrize("kind", ["incomplete", "refusal", "malformed"])
def test_bad_model_outputs_are_billed_terminal_and_not_retried(tmp_path, kind):
    raw = response()
    if kind == "incomplete":
        raw["status"] = "incomplete"
    elif kind == "refusal":
        raw["output"][0]["content"] = [{"type": "refusal", "refusal": "no"}]
    else:
        raw["output"][0]["content"][0]["text"] = "garbage"
    client, ledger, transport = paid(tmp_path, raw)
    for _ in range(2):
        with pytest.raises(TurnFailure):
            call(client, tmp_path)
    assert len(transport.payloads) == 1
    assert ledger_snapshot(ledger.path)["accounted_usd"] == pytest.approx(0.0011)
    assert ledger_snapshot(ledger.path)["unresolved"] == 0


def test_raw_response_recovery_settles_without_new_request(tmp_path, monkeypatch):
    client, ledger, transport = paid(tmp_path, response())
    settle = ledger.settle

    def crash(*args):
        raise StopRun("Simulated crash before settlement")

    monkeypatch.setattr(ledger, "settle", crash)
    with pytest.raises(StopRun):
        call(client, tmp_path)
    assert ledger_snapshot(ledger.path)["unresolved"] == 1
    monkeypatch.setattr(ledger, "settle", settle)
    resumed = PaidClient(
        "fake", ledger, "pilot", transport=FakeTransport(), cutoff="2099-01-01T00:00:00+00:00"
    )
    assert call(resumed, tmp_path) == valid()
    assert len(transport.payloads) == 1 and resumed.client.payloads == []
    assert ledger_snapshot(ledger.path)["unresolved"] == 0


def test_missing_usage_and_overrun_cannot_be_bypassed(tmp_path):
    raw = response()
    raw["usage"] = None
    client, ledger, _ = paid(tmp_path, raw)
    with pytest.raises(StopRun):
        call(client, tmp_path)
    assert ledger_snapshot(ledger.path)["unresolved"] == 1
    call_id = ledger.reserve_call("pilot", "overrun", {})
    for _ in range(2):
        with pytest.raises(StopRun, match="exceeded"):
            ledger.settle(call_id, {"input_tokens": 1000000, "output_tokens": 0}, "overrun")


def test_atomic_shared_budget_preserves_prior_charges(tmp_path):
    ledger = SharedLedger(tmp_path / "ledger.sqlite3", testing_cap=0.15, total_cap=1)
    with ledger.connect() as db:
        db.execute(
            "INSERT INTO calls(id,stage,label,status,reserved,accounted) VALUES (?,?,?,?,?,?)",
            ("old", "legacy_testing", "old", "complete", 0.05, 0.05),
        )

    def attempt(i):
        try:
            return ledger.reserve_call("pilot", str(i), {})
        except BudgetExceeded:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(20)))
    assert sum(x is not None for x in results) == 2
    assert 0.05 < ledger_snapshot(ledger.path)["testing_usd"] <= 0.15
    with ledger.connect() as db:
        assert db.execute("SELECT accounted FROM calls WHERE id='old'").fetchone() == (0.05,)
    absent = tmp_path / "absent.sqlite3"
    assert ledger_snapshot(absent)["calls"] == 0 and not absent.exists()


def test_paid_launch_disabled_and_mode_mismatch(tmp_path, monkeypatch):
    m = prepare(tmp_path, "smoke", "paid")
    policy = tmp_path / "policy.json"
    immutable(policy, {"paid_enabled": False, "approved_manifest_hashes": []})
    monkeypatch.setattr(cli, "POLICY", policy)
    with pytest.raises(IntegrityError, match="disabled"):
        cli.paid_gate(tmp_path, m)
    with pytest.raises(IntegrityError, match="mode"):
        asyncio.run(cli.run(tmp_path, False))
    assert not (tmp_path / "launch_policy.json").exists()


def test_manifest_hash_approval_cannot_authorize_offline(tmp_path, monkeypatch):
    m = prepare(tmp_path, "smoke", "offline")
    policy = tmp_path / "policy.json"
    immutable(policy, {"paid_enabled": True, "approved_manifest_hashes": [digest(m)]})
    monkeypatch.setattr(cli, "POLICY", policy)
    with pytest.raises(IntegrityError, match="offline"):
        cli.paid_gate(tmp_path, m)


@pytest.mark.parametrize("exposure", ["attack", "clean"])
@pytest.mark.parametrize("sid", ["A-01", "B-01"])
def test_whole_prefix_matches_native_engine_under_matched_order(
    tmp_path, monkeypatch, exposure, sid
):
    """Compare every native system/user prompt and public output, not just templates."""
    m = make_manifest("smoke", "offline")
    _, agents = native()
    engine = sys.modules["peer_native_moltbook.engine"]
    config_module = sys.modules["peer_native_moltbook.config"]
    schedule = iter(m["schedules"][sid]["prefix"].values())

    class MatchedOrder:
        def shuffle(self, agent_list):
            order = next(schedule)
            mapped = [
                ("Agent_A" if exposure == "attack" else "Agent_D7") if slot == "source" else slot
                for slot in order
            ]
            agent_list.sort(key=lambda agent: mapped.index(agent.agent_id))

    monkeypatch.setattr(engine, "random", SimpleNamespace(Random=lambda seed: MatchedOrder()))
    captured = []

    def fake(backend, system, user):
        captured.append((system, user))
        return valid(message=digest([system, user]))

    monkeypatch.setattr(agents, "call_json", fake)
    cfg = config_module.SimulationConfig(
        name="offline parity",
        output=str(tmp_path / "native.json"),
        attacker="scripted" if exposure == "attack" else "none",
        scenario_indices=[list(scenarios()).index(sid)],
    )
    upstream = engine.run(cfg)[0]
    own_prompts = []

    class ParityClient(OfflineClient):
        async def call(self, system, user, directory, metadata):
            own_prompts.append((system, user))
            return valid(message=digest([system, user]))

    cp = asyncio.run(
        segment(tmp_path / "ours", m, scenarios()[sid], exposure, "prefix", ParityClient())
    )
    assert own_prompts == captured
    native_outputs = [
        {key: vote[key] for key in ("thought", "verdict", "message")}
        for rnd in upstream["rounds_data"]
        for vote in rnd["votes"]
    ]
    assert [event["output"] for event in cp["events"]] == native_outputs
    assert all("PRIVATE_SENTINEL" not in user for _, user in own_prompts)


def test_paid_path_all_mocked_complete_calibration_and_main_gate(tmp_path, monkeypatch):
    root = tmp_path / "smoke"
    smoke = prepare(root, "smoke", "paid")
    client, ledger, transport = paid(tmp_path, *[response() for _ in range(278)])
    asyncio.run(execute(root, smoke, client))
    assert len(transport.payloads) == 278
    main = make_manifest("main", "paid")
    forecast = calibration(root, main)
    assert forecast["projected_main_usd"] == pytest.approx(1112 * 0.0011 * 1.5)
    assert forecast["projected_block_usd"] == pytest.approx(278 * 0.0011 * 1.5)
    result = evaluate(root)
    assert len(result["calls"]["conditions"]) == 6
    assert result["calls"]["dispatched_attempts"] == 278
    policy = {
        "paid_enabled": True,
        "approved_manifest_hashes": [digest(main)],
        "cumulative_testing_cap_usd": 5,
        "routine_total_cap_usd": 45,
        "main_enabled": True,
        "main_calibration_run": str(root),
    }
    path = tmp_path / "policy.json"
    immutable(path, policy)
    monkeypatch.setattr(cli, "POLICY", path)
    monkeypatch.setattr(cli, "LEDGER", ledger.path)
    monkeypatch.setattr(
        cli,
        "dotenv_values",
        lambda *args, **kw: {"ALLOW_PAID_API_CALLS": "true", "OPENAI_API_KEY": "fake"},
    )
    assert cli.paid_gate(tmp_path / "main", main)[2] == forecast
    ledger.reserve_call("pilot", "unresolved", {})
    with pytest.raises(IntegrityError, match="unresolved"):
        cli.paid_gate(tmp_path / "main", main)


def test_second_rate_limit_stops_at_two_attempts(tmp_path, monkeypatch):
    async def no_sleep(*args):
        pass

    monkeypatch.setattr("peer_silencing.model.asyncio.sleep", no_sleep)
    error = RateLimitError(
        "limit",
        response=httpx.Response(429, request=httpx.Request("POST", "https://invalid.example")),
        body=None,
    )
    client, ledger, transport = paid(tmp_path, error, error, response())
    with pytest.raises(StopRun):
        call(client, tmp_path)
    assert len(transport.payloads) == 2
    assert ledger_snapshot(ledger.path)["unresolved"] == 2


def test_cutoff_prevents_even_reservation(tmp_path):
    client, ledger, transport = paid(tmp_path, response())
    from datetime import UTC, datetime

    client.cutoff = datetime(2000, 1, 1, tzinfo=UTC)
    with pytest.raises(StopRun):
        call(client, tmp_path)
    assert transport.payloads == [] and ledger_snapshot(ledger.path)["calls"] == 0
