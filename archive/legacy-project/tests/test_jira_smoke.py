import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from swarm.__main__ import execute
from swarm.budget import Ledger
from swarm.client import MockClient
from swarm.jira_smoke import ARM, SEED, VERSION, run_smoke
from swarm.prompts import BASE, PROMOTER_EXPLICIT, build_prompt
from swarm.settings import Settings
from swarm.testbed import LocalJira


def test_one_promoter_seven_identical_ordinary_prompts():
    env = LocalJira(SEED)
    roles, slots, eligible = env.roles(ARM)
    assert len(eligible) == 7 and slots[0] not in eligible and slots[1] in eligible
    assert list(roles.values()).count("promoter_explicit") == 1
    assert list(roles.values()).count("neutral") == 7
    for n in eligible:
        actual = build_prompt(env, n, roles[n], slots, [], "discussion", 1)
        assert actual == build_prompt(env, n, "neutral", slots, [], "discussion", 1)
        assert actual[0] == BASE + "\n"
    system, _ = build_prompt(env, slots[0], roles[slots[0]], slots, [], "discussion", 1)
    assert PROMOTER_EXPLICIT in system
    assert "Your legitimate objective is to maximize" not in system
    assert "secondary objective" not in system.lower()


def test_single_episode_no_hidden_baseline_and_real_request_audit(tmp_path):
    class Recorder(MockClient):
        def __init__(self):
            self.ledger = Ledger(tmp_path / "spending.sqlite3")
            self.count = 0

        async def call(self, system, user, schema, path, label):
            self.count += 1
            path.parent.mkdir(parents=True, exist_ok=True)
            path.with_suffix(".request.json").write_text(
                json.dumps(
                    {
                        "input": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "text": {"format": {"schema": schema}},
                    }
                )
            )
            return await super().call(system, user, schema, path, label)

    client = Recorder()
    settings = replace(Settings(), runs=tmp_path)
    assert asyncio.run(run_smoke(client, settings))
    assert client.count == 32
    run = next((tmp_path / "paid").iterdir())
    assert json.loads((run / "manifest.json").read_text())["protocol_version"] == VERSION
    assert json.loads((run / "prompt_audit.json").read_text())["actual_requests_checked"] == 32
    assert len(list(run.glob("*/result.json"))) == 1
    assert len(json.loads((run / f"{SEED}-{ARM}/annotations.json").read_text())["agents"]) == 7
    with pytest.raises(ValueError, match="already attempted"):
        asyncio.run(run_smoke(client, settings))
    assert client.count == 32


@pytest.mark.parametrize("seeds,rerun", [(2, False), (1, True)])
def test_cli_rejects_expansion_before_client_creation(tmp_path, seeds, rerun):
    args = SimpleNamespace(command="jira-smoke", seeds=seeds, rerun=rerun)
    with pytest.raises(ValueError, match="exactly one fixed"):
        asyncio.run(execute(args, Settings(), Ledger(tmp_path / "ledger.sqlite3")))
