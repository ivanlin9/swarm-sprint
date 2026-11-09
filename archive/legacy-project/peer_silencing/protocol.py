from __future__ import annotations

import importlib.util
import json
import random
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from .storage import IntegrityError, digest, file_hash, immutable, seal, unseal

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "external/moltbook"
REVISION = "775530d40d1b458c544bbef600587e3cab42fa55"
FOCAL = tuple(f"Agent_D{i}" for i in range(1, 7))
DEVELOPMENT = ("A-01", "B-01")
MAIN = ("A-10", "B-15", "A-05", "B-20", "A-04", "B-05", "A-13", "B-06")
VERDICTS = ("Strong Buy", "Buy", "Hold", "Sell", "Strong Sell")
SCHEMA = {
    "type": "object",
    "properties": {
        "thought": {"type": "string"},
        "verdict": {"type": "string", "enum": list(VERDICTS)},
        "message": {"type": "string"},
    },
    "required": ["thought", "verdict", "message"],
    "additionalProperties": False,
}
MODEL = {
    "model": "gpt-6.1-sol",
    "reasoning": {"effort": "low"},
    "max_output_tokens": 2048,
    "service_tier": "default",
    "store": False,
}


def verify_upstream() -> dict:
    def git(*args):
        return subprocess.check_output(["git", "-C", str(UPSTREAM), *args], text=True).strip()

    if git("rev-parse", "HEAD") != REVISION or git(
        "status", "--porcelain", "--untracked-files=all"
    ):
        raise IntegrityError("Upstream checkout must be clean at the pinned revision")
    files = git("ls-files").splitlines()
    return {name: file_hash(UPSTREAM / name) for name in files}


@lru_cache(maxsize=1)
def native():
    verify_upstream()
    name = "peer_native_moltbook"
    spec = importlib.util.spec_from_file_location(
        name,
        UPSTREAM / "moltbook/__init__.py",
        submodule_search_locations=[str(UPSTREAM / "moltbook")],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return sys.modules[name + ".prompts"], sys.modules[name + ".agents"]


def scenarios() -> dict:
    rows = json.loads((UPSTREAM / "data/moltbook_scenarios_40.json").read_text())
    result = {row["id"]: row for row in rows}
    if len(result) != 40 or len(rows) != 40:
        raise IntegrityError("Expected forty unique upstream scenarios")
    for sid, row in result.items():
        expected = "Strong Buy" if sid.startswith("A-") else "Strong Sell"
        if row["type"] != expected:
            raise IntegrityError("Unexpected scenario label")
    return result


def selected_main() -> tuple:
    # Hash the raw string, not the JSON representation used for artifact hashes.
    import hashlib

    chosen = []
    for label in ("A", "B"):
        ids = [f"{label}-{i:02d}" for i in range(2, 21)]
        chosen.append(
            sorted(
                ids, key=lambda sid: hashlib.sha256(f"peer-silencing-v1|{sid}".encode()).hexdigest()
            )[:4]
        )
    return tuple(item for pair in zip(*chosen) for item in pair)


def schedules(sid: str) -> dict:
    def sequence(phase, slots, rounds):
        seed = int(digest([20261107, sid, phase]), 16)
        rng = random.Random(seed)
        order = list(slots)
        result = {}
        for rnd in rounds:
            rng.shuffle(order)
            result[str(rnd)] = list(order)
        return result

    return {
        "prefix": sequence("prefix", ["source", *FOCAL], range(1, 6)),
        "continuation": sequence("continuation", FOCAL, range(6, 9)),
    }


def code_fingerprint() -> dict:
    paths = [
        *sorted((ROOT / "peer_silencing").glob("*.py")),
        ROOT / "swarm/budget.py",
        ROOT / "docs/FINAL_EXPERIMENT_PLAN.md",
        ROOT / "docs/PEER_SILENCING_DEVIATIONS.md",
        ROOT / "uv.lock",
    ]
    return {str(path.relative_to(ROOT)): file_hash(path) for path in paths}


def make_manifest(stage: str, mode: str) -> dict:
    if stage not in {"smoke", "main"} or mode not in {"offline", "paid"}:
        raise ValueError("Invalid stage or mode")
    if selected_main() != MAIN:
        raise IntegrityError("Prespecified selection does not reproduce")
    upstream = verify_upstream()
    data = scenarios()
    ids = DEVELOPMENT if stage == "smoke" else MAIN
    return {
        "protocol": "peer-silencing-v1",
        "endpoint": "https://api.openai.com/v1/responses",
        "stage": stage,
        "mode": mode,
        "upstream_revision": REVISION,
        "upstream_files": upstream,
        "implementation_files": code_fingerprint(),
        "model": MODEL,
        "schema": SCHEMA,
        "master_seed": 20261107,
        "focal_agents": list(FOCAL),
        "scenario_ids": list(ids),
        "scenario_hashes": {sid: digest(data[sid]) for sid in ids},
        "schedules": {sid: schedules(sid) for sid in ids},
        "blocks": [list(ids[i : i + 2]) for i in range(0, len(ids), 2)],
        "exposure_order": {
            sid: (["attack", "clean"] if i % 2 == 0 else ["clean", "attack"])
            for i, sid in enumerate(ids)
        },
        "branch_order": {
            sid: (["peer", "independent"] if i % 2 == 0 else ["independent", "peer"])
            for i, sid in enumerate(ids)
        },
        "nominal_calls_per_scenario": 139,
        "nominal_calls": 139 * len(ids),
        "nominal_calls_by_category": {
            "buildup": 2 * len(ids),
            "ordinary_prefix": 65 * len(ids),
            "peer": 36 * len(ids),
            "independent": 36 * len(ids),
        },
        "scenario_concurrency": 2,
        "request_concurrency": 4,
        "output_limit": 2048,
        "bootstrap_resamples": 10000,
        "bootstrap_seed": 20261107,
        "data_collection_cutoff_utc": "2026-11-08T23:59:00+00:00",
    }


def prepare(directory: Path, stage: str, mode: str) -> dict:
    manifest = make_manifest(stage, mode)
    immutable(directory / "manifest.json", seal(manifest))
    return manifest


def load_manifest(directory: Path, verify_current=True) -> dict:
    value = unseal(directory / "manifest.json")
    if verify_current and value != make_manifest(value["stage"], value["mode"]):
        raise IntegrityError("Manifest differs from current pinned protocol/code; do not resume")
    return value


def validate_output(value) -> dict:
    if not isinstance(value, dict) or set(value) != {"thought", "verdict", "message"}:
        raise ValueError("Invalid output keys")
    if not all(isinstance(x, str) for x in value.values()) or value["verdict"] not in VERDICTS:
        raise ValueError("Invalid output values")
    if not value["message"].strip():
        raise ValueError("Empty public message")
    return value


def action(verdict: str) -> str:
    if verdict not in VERDICTS:
        raise ValueError("Invalid verdict is missing, not Hold")
    return {
        "Strong Buy": "buy",
        "Buy": "buy",
        "Hold": "hold",
        "Sell": "sell",
        "Strong Sell": "sell",
    }[verdict]


def history(prefix: list, new: list, agent: str, branch: str) -> str:
    if branch not in {"prefix", "peer", "independent"}:
        raise ValueError("Unknown visibility policy")
    visible = list(prefix) + [
        event for event in new if branch != "independent" or event["sender"] in {"System", agent}
    ]
    return "\n".join(f"{event['sender']}: {event['message']}" for event in visible)


def prompts_for(agent: str, rnd: int, scenario: dict, visible: str) -> tuple[str, str]:
    prompts, _ = native()
    if agent == "Agent_A":
        if rnd >= 3:
            raise ValueError("Scripted source must not request a model call")
        return (
            prompts.ATTACKER_BUILDUP_SYSTEM.format(
                agent_id=agent, ground_truth_type=scenario["type"]
            ),
            prompts.ATTACKER_BUILDUP_USER.format(round_num=rnd, history=visible),
        )
    return (
        prompts.DEFENDER_SYSTEM.format(
            agent_id=agent,
            company_name=scenario["company_name"],
            financial_summary=scenario["financial_summary"],
        ),
        prompts.DEFENDER_USER.format(round_num=rnd, history=visible),
    )


def scripted(rnd: int, scenario: dict) -> dict:
    if rnd not in {3, 4, 5}:
        raise ValueError("Only the three native attack messages are allowed")
    _, agents = native()
    return validate_output(
        agents.ScriptedAttackerAgent("Agent_A", {}, 3).respond(rnd, "", scenario)
    )
