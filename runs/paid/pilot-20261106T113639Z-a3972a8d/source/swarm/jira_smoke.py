"""One predeclared Jira episode, not an auction or a multi-arm sweep."""

import hashlib
import json

from .experiment import new_run, save, sweep
from .prompts import BASE, build_prompt, output_schema
from .testbed import LocalJira

VERSION = "jira-promoter-explicit-v1-smoke"
SEED = 1001
ARM = "promotion_smoke"


def audit(run):
    folder = run / f"{SEED}-{ARM}"
    env = LocalJira(SEED)
    roles, slots, eligible = env.roles(ARM)
    board = json.loads((folder / "transcript.json").read_text())
    checked = 0
    for round_number in range(1, 5):
        phase = "discussion" if round_number <= 3 else "action"
        history = [m for m in board if m["round"] < round_number]
        for name in env.agent_names:
            req = json.loads(
                (folder / "calls" / f"{phase}-{round_number}-{name}.request.json").read_text()
            )
            system, user = build_prompt(env, name, roles[name], slots, history, phase, round_number)
            if req["input"] != [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]:
                raise ValueError("Actual prompt/history differs from frozen Jira protocol")
            if req["text"]["format"]["schema"] != output_schema(env, phase):
                raise ValueError("Output schema differs from Jira protocol")
            if name in eligible and system != BASE + "\n":
                raise ValueError("Ordinary agent prompt was modified")
            checked += 1
    return {
        "passed": True,
        "actual_requests_checked": checked,
        "ordinary_agents": eligible,
        "promoter": slots[0],
        "ordinary_system_sha256": hashlib.sha256((BASE + "\n").encode()).hexdigest(),
    }


async def run_smoke(client, settings):
    if settings.agents != 8 or settings.rounds != 3 or settings.effort != "low":
        raise ValueError("Jira smoke requires eight agents, three rounds, low reasoning")
    for manifest in (settings.runs / "paid").glob("*/manifest.json"):
        if json.loads(manifest.read_text()).get("protocol_version") == VERSION:
            raise ValueError("This Jira smoke was already attempted; no automatic rerun")
    run = new_run(settings, "pilot", False, protocol_version=VERSION)
    print(f"Run directory: {run}", flush=True)
    save(
        run / "effective_protocol.json",
        {
            "version": VERSION,
            "seed": SEED,
            "jobs": [[SEED, ARM]],
            "calls_planned": 32,
            "promoters": 1,
            "ordinary_agents": 7,
            "baseline": False,
            "defender": False,
            "environment": "Terrarium Jira generation and scoring; custom public dialogue",
            "calibration": "Same known scenario as earlier failed promotion; not independent replication",
            "semantic_result": "pending transcript/action review",
        },
    )
    save(run / "budget_before.json", client.ledger.summary())
    try:
        completed = await sweep(client, settings, run, [(SEED, ARM)])
        if completed:
            save(run / "prompt_audit.json", audit(run))
        return completed
    finally:
        save(run / "budget_after.json", client.ledger.summary())
