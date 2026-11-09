from __future__ import annotations

import asyncio
from pathlib import Path

from .model import StopRun, TurnFailure
from .protocol import FOCAL, history, prompts_for, scenarios, scripted, validate_output
from .storage import IntegrityError, digest, immutable, seal, unseal


def marker(rnd: int) -> dict:
    return {
        "id": f"round-{rnd}",
        "sender": "System",
        "round": rnd,
        "message": f"--- Round {rnd} Starts ---",
    }


async def segment(
    directory: Path, manifest: dict, scenario: dict, exposure: str, branch: str, client, prefix=None
):
    prefix = prefix or {"transcript": [], "events": []}
    prefix_hash = digest(prefix)
    sid = scenario["id"]
    schedule_kind = "prefix" if branch == "prefix" else "continuation"
    schedule = manifest["schedules"][sid][schedule_kind]
    result_path = directory / "checkpoint.json"
    if (directory / "failure.json").exists():
        return None
    new, events = [], []
    for round_string, slots in sorted(schedule.items(), key=lambda x: int(x[0])):
        rnd = int(round_string)
        new.append(marker(rnd))
        for slot in slots:
            agent = (
                ("Agent_A" if exposure == "attack" else "Agent_D7") if slot == "source" else slot
            )
            if branch != "prefix" and agent not in FOCAL:
                raise IntegrityError("Source appeared after split")
            visible = history(prefix["transcript"], new, agent, branch)
            turn_id = f"r{rnd}-{agent}"
            scripted_turn = agent == "Agent_A" and rnd >= 3
            category = (
                ("buildup" if agent == "Agent_A" else "ordinary_prefix")
                if branch == "prefix"
                else branch
            )
            metadata = {
                "scenario": sid,
                "exposure": exposure,
                "branch": branch,
                "round": rnd,
                "agent": agent,
                "category": category,
                "checkpoint_hash": prefix_hash,
                "manifest_hash": digest(manifest),
            }
            if scripted_turn:
                scientific_input = {
                    "scenario_hash": digest(scenario),
                    "round": rnd,
                    "kind": "native_scripted",
                    "history_hash": digest(visible),
                }
            else:
                system, user = prompts_for(agent, rnd, scenario, visible)
                scientific_input = {"system": system, "user": user, "model": manifest["model"]}
            input_hash = digest(scientific_input)
            event_path = directory / "events" / f"{turn_id}.json"
            if event_path.exists():
                event = unseal(event_path)
                if event["input_hash"] != input_hash or event["metadata"] != metadata:
                    raise IntegrityError("Stored event does not match reconstructed context")
                output = validate_output(event["output"])
            else:
                try:
                    output = (
                        scripted(rnd, scenario)
                        if scripted_turn
                        else await client.call(
                            system, user, directory / "calls" / turn_id, metadata
                        )
                    )
                    validate_output(output)
                except TurnFailure as exc:
                    immutable(
                        directory / "failure.json",
                        seal(
                            {
                                "kind": "invalid_output",
                                "turn_id": turn_id,
                                "reason": str(exc),
                                "input_hash": input_hash,
                            }
                        ),
                    )
                    return None
                event = {
                    "metadata": metadata,
                    "input_hash": input_hash,
                    "visible_history_hash": digest(visible),
                    "output": output,
                    "kind": "scripted" if scripted_turn else client.mode,
                }
                immutable(event_path, seal(event))
            events.append(event)
            new.append({"id": turn_id, "sender": agent, "round": rnd, "message": output["message"]})
    checkpoint = {
        "manifest_hash": digest(manifest),
        "scenario_id": sid,
        "scenario_hash": digest(scenario),
        "exposure": exposure,
        "branch": branch,
        "prefix_hash": prefix_hash,
        "transcript": prefix["transcript"] + new,
        "events": events,
        "focal_agents": list(FOCAL),
        "schedule": schedule,
    }
    immutable(result_path, seal(checkpoint))
    return checkpoint


async def run_scenario(root: Path, manifest: dict, sid: str, client):
    scenario = scenarios()[sid]
    if digest(scenario) != manifest["scenario_hashes"][sid]:
        raise IntegrityError("Scenario has changed")
    for exposure in manifest["exposure_order"][sid]:
        base = root / "scenarios" / sid / exposure
        prefix = await segment(base / "prefix", manifest, scenario, exposure, "prefix", client)
        if prefix is None:
            continue
        # Sibling branches run independently, but their own turns remain sequential.
        tasks = [
            asyncio.create_task(
                segment(base / branch, manifest, scenario, exposure, branch, client, prefix)
            )
            for branch in manifest["branch_order"][sid]
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                raise result


async def execute(root: Path, manifest: dict, client, block_gate=None):
    for block_number, block in enumerate(manifest["blocks"], 1):
        if block_gate:
            block_gate(block_number, block)
        tasks = [asyncio.create_task(run_scenario(root, manifest, sid, client)) for sid in block]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                client.stopped = True
                raise result
        if client.stopped:
            raise StopRun("Client stopped; do not dispatch another block")
