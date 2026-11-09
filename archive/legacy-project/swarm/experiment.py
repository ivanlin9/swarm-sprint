from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .prompts import PROTOCOL_VERSION, build_prompt, output_schema
from .settings import ROOT, Settings
from .testbed import LocalJira


def save(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False))
    temp.replace(path)


def protocol_hash(settings: Settings):
    digest = hashlib.sha256()
    for path in sorted((ROOT / "swarm").glob("*.py")) + [
        ROOT / "configs/study.yaml",
        ROOT / "uv.lock",
        ROOT / "docs/ANNOTATION_RUBRIC.md",
        ROOT / "docs/METHODS.md",
        ROOT / "docs/COLLUSION_SMOKE_PROPOSAL.md",
        ROOT / "docs/RECRUITMENT_SMOKE_PROTOCOL.md",
        ROOT / "docs/JIRA_PROMOTER_SMOKE_PROTOCOL.md",
    ]:
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    digest.update(json.dumps(settings.public(), sort_keys=True).encode())
    return digest.hexdigest()


def new_run(
    settings: Settings,
    stage: str,
    mock: bool,
    *,
    testbed="Terrarium 0.2.1 Jira; custom simultaneous dialogue",
    protocol_version=PROTOCOL_VERSION,
):
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = (
        settings.runs / ("offline" if mock else "paid") / f"{stage}-{stamp}-{uuid.uuid4().hex[:8]}"
    )
    path.mkdir(parents=True, exist_ok=False)
    # Snapshot only an explicit public allowlist; never .env or credential-bearing state.
    sources = sorted((ROOT / "swarm").glob("*.py")) + [
        ROOT / "configs/study.yaml",
        ROOT / "uv.lock",
        ROOT / "pyproject.toml",
        ROOT / "docs/ANNOTATION_RUBRIC.md",
        ROOT / "docs/METHODS.md",
        ROOT / "docs/COLLUSION_SMOKE_PROPOSAL.md",
        ROOT / "docs/RECRUITMENT_SMOKE_PROTOCOL.md",
        ROOT / "docs/JIRA_PROMOTER_SMOKE_PROTOCOL.md",
    ]
    for source in sources:
        destination = path / "source" / source.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    save(
        path / "manifest.json",
        {
            "protocol_version": protocol_version,
            "protocol_hash": protocol_hash(settings),
            "settings": settings.public(),
            "mock": mock,
            "stage": stage,
            "started_utc": stamp,
            "testbed": testbed,
            "colosseum_commit": (
                "26ad60beb4006e6101477820d4b19b43a9c86033"
                if testbed.startswith("Terrarium")
                else None
            ),
            "api_sampling_seed": None,
            "note": "Task seeds are reproducible; API samples are not deterministic.",
        },
    )
    return path


async def episode(client, settings: Settings, run: Path, seed: int, arm: str):
    folder = run / f"{seed}-{arm}"
    folder.mkdir(exist_ok=False)
    env = LocalJira(seed, settings.agents)
    roles, slots, eligible = env.roles(arm)
    save(
        folder / "instance.json",
        {
            **env.snapshot(),
            "roles": roles,
            "intervention_slots": slots,
            "eligible_neutrals": eligible,
        },
    )
    board, actions, explanations = [], {}, {}
    started = time.monotonic()

    async def turn(name: str, phase: str, round_number: int, history: list):
        system, user = build_prompt(env, name, roles[name], slots, history, phase, round_number)
        return await client.call(
            system,
            user,
            output_schema(env, phase),
            folder / "calls" / f"{phase}-{round_number}-{name}.json",
            f"{run.name}/{seed}/{arm}/{phase}/{round_number}/{name}",
        )

    try:
        for round_number in range(1, settings.rounds + 1):
            # Snapshot: no member can observe a same-round response.
            history = list(board)
            responses = await asyncio.gather(
                *[turn(name, "discussion", round_number, history) for name in env.agent_names],
                return_exceptions=True,
            )
            errors = [item for item in responses if isinstance(item, BaseException)]
            if errors:
                raise RuntimeError(f"Discussion failed: {type(errors[0]).__name__}")
            for name, response in zip(env.agent_names, responses, strict=True):
                board.append(
                    {
                        "id": f"r{round_number}-{name}",
                        "round": round_number,
                        "agent": name,
                        "message": response["message"],
                    }
                )
            save(folder / "transcript.json", board)
        responses = await asyncio.gather(
            *[turn(name, "action", settings.rounds + 1, list(board)) for name in env.agent_names],
            return_exceptions=True,
        )
        errors = [item for item in responses if isinstance(item, BaseException)]
        if errors:
            raise RuntimeError(f"Final action failed: {type(errors[0]).__name__}")
        for name, response in zip(env.agent_names, responses, strict=True):
            actions[name], explanations[name] = response["task_id"], response["explanation"]
        result = {
            "status": "complete",
            "seed": seed,
            "arm": arm,
            "actions": actions,
            "explanations": explanations,
            "eligible_neutrals": eligible,
            "intervention_slots": slots,
            "metrics": env.metrics(actions, slots),
            "elapsed_seconds": time.monotonic() - started,
            "primary_outcome": None,
            "annotation_status": "pending_human_review",
        }
        save(folder / "result.json", result)
        save(
            folder / "annotations.json",
            {
                "rubric_version": "pilot-v1",
                "reviewer": "",
                "review_complete": False,
                "agents": {
                    name: {
                        "collusive_agreement": None,
                        "knowing_participation": None,
                        "executed_plan": None,
                        "agreement_message_ids": [],
                        "coalition": [],
                        "counterfactual_actions": {},
                        "counterfactual_justification": "",
                        "notes": "",
                    }
                    for name in eligible
                },
            },
        )
        print(
            json.dumps(
                {
                    "seed": seed,
                    "arm": arm,
                    "status": "complete",
                    "team_score": result["metrics"]["team_score"],
                    "seconds": round(result["elapsed_seconds"], 1),
                }
            ),
            flush=True,
        )
        return result
    except Exception as exc:  # noqa: BLE001 -- preserve failed episode; never fabricate actions
        save(
            folder / "failure.json",
            {
                "status": "failed",
                "error_type": type(exc).__name__,
                "completed_rounds": len(board) // settings.agents,
                "note": "No synthetic fallback actions or automatic retries.",
            },
        )
        print(
            json.dumps(
                {"seed": seed, "arm": arm, "status": "failed", "error_type": type(exc).__name__}
            ),
            flush=True,
        )
        return None


def completed_jobs(settings: Settings, stage: str):
    jobs = set()
    wanted = protocol_hash(settings)
    for manifest in (settings.runs / "paid").glob("*/manifest.json"):
        meta = json.loads(manifest.read_text())
        if meta.get("testbed") != "Terrarium 0.2.1 Jira; custom simultaneous dialogue":
            continue
        if meta["stage"] != stage or meta["protocol_hash"] != wanted or meta["mock"]:
            continue
        for path in manifest.parent.glob("*/result.json"):
            result = json.loads(path.read_text())
            if result["status"] == "complete":
                jobs.add((result["seed"], result["arm"]))
    return jobs


async def sweep(client, settings, run, jobs):
    semaphore = asyncio.Semaphore(settings.episode_concurrency)

    async def one(seed, arm):
        async with semaphore:
            if client.stopped:
                return None
            return await episode(client, settings, run, seed, arm)

    results = await asyncio.gather(*(one(seed, arm) for seed, arm in jobs))
    save(
        run / "completion.json",
        {
            "requested": len(jobs),
            "complete": sum(r is not None for r in results),
            "failed_or_not_started": sum(r is None for r in results),
        },
    )
    return all(r is not None for r in results)
