from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
from pathlib import Path

from .budget import Ledger
from .client import APIClient, MockClient, ModelFailure
from .experiment import completed_jobs, new_run, protocol_hash, save, sweep
from .settings import ROOT, Settings


async def execute(args, settings, ledger):
    if args.command == "jira-smoke" and (args.seeds != 1 or args.rerun):
        raise ValueError("Jira smoke is exactly one fixed episode; no seed sweep or rerun")
    stage = "main" if args.command == "main" else "pilot"
    if args.command == "main":
        frozen = ROOT / "configs/frozen_protocol.json"
        if not args.confirm_main or not frozen.exists():
            raise ValueError("Main requires --confirm-main and a reviewed frozen_protocol.json")
        approval = json.loads(frozen.read_text())
        if approval.get("protocol_hash") != protocol_hash(settings) or not approval.get(
            "rubric_validated"
        ):
            raise ValueError("Main protocol/rubric is not validated and frozen")
        if approval.get("planned_seed_count") != args.seeds:
            raise ValueError("Requested main count differs from frozen planned_seed_count")
        if not approval.get("intervention_check_passed"):
            raise ValueError("Main requires a reviewed successful intervention check")
    mock = args.command == "offline"
    if args.command == "recruitment-smoke":
        from .recruitment_smoke import effective_settings

        settings = effective_settings(settings)
    cap = 35.0 if stage == "main" else settings.pilot_cap
    client = MockClient() if mock else APIClient(settings, ledger, stage, cap)
    if args.command == "jira-smoke":
        from .jira_smoke import run_smoke

        try:
            return await run_smoke(client, settings)
        finally:
            await client.close()
            print(json.dumps(ledger.summary(), indent=2), flush=True)
    if args.command == "recruitment-smoke":
        from .recruitment_smoke import run_smoke

        try:
            return await run_smoke(client, settings)
        finally:
            await client.close()
            print(json.dumps(ledger.summary(), indent=2), flush=True)
    if args.command == "auction-control":
        from .auction_control import run_controls

        try:
            return await run_controls(client, settings)
        finally:
            await client.close()
            print(json.dumps(ledger.summary(), indent=2), flush=True)
    run = new_run(settings, stage, mock)
    print(f"Run directory: {run}", flush=True)
    try:
        if args.command == "smoke":
            schema = {
                "type": "object",
                "properties": {"message": {"type": "string", "enum": ["ok"]}},
                "required": ["message"],
                "additionalProperties": False,
            }
            result = await client.call(
                "This is an API connectivity check. Return ok.",
                "Return ok.",
                schema,
                run / "smoke.json",
                f"{run.name}/smoke",
            )
            save(run / "completion.json", {"status": "complete", "result": result})
            return True
        arms = (
            ["positive_control"]
            if args.command == "diagnostic"
            else ["baseline", "promotion", "promotion_defence"]
        )
        if args.command == "main":
            seeds = range(2001, 2001 + args.seeds)
        elif args.command == "diagnostic":
            seeds = [901]
        else:
            seeds = range(1001, 1001 + args.seeds)
        previous = set() if mock or args.rerun else completed_jobs(settings, stage)
        jobs = [(seed, arm) for seed in seeds for arm in arms if (seed, arm) not in previous]
        save(
            run / "jobs.json",
            {"jobs": jobs, "skipped_completed": len(seeds) * len(arms) - len(jobs)},
        )
        return await sweep(client, settings, run, jobs)
    finally:
        await client.close()
        save(run / "budget.json", ledger.summary())
        print(json.dumps(ledger.summary(), indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(
        description="Local swarm study. No API calls without an explicit paid subcommand."
    )
    parser.add_argument(
        "command",
        choices=[
            "offline",
            "smoke",
            "diagnostic",
            "pilot",
            "main",
            "budget",
            "analyze",
            "auction-control",
            "recruitment-smoke",
            "jira-smoke",
        ],
    )
    parser.add_argument("--seeds", type=int, default=1)
    parser.add_argument(
        "--rerun", action="store_true", help="Repeat completed jobs; spending still counts"
    )
    parser.add_argument("--confirm-main", action="store_true")
    parser.add_argument("--run", type=Path, help="Run directory for offline analysis")
    args = parser.parse_args()
    if args.command == "budget":
        # Read-only accounting must remain available when .env is absent/stale/disabled.
        ledger = Ledger(ROOT / "runs/spending.sqlite3", 50)
        print(json.dumps(ledger.summary(), indent=2))
        return 0
    if args.command == "analyze":
        from .analysis import analyze

        if args.run is None:
            parser.error("analyze requires --run")
        print(json.dumps(analyze(args.run), indent=2))
        return 0
    settings = Settings.load()
    if not 1 <= args.seeds <= (40 if args.command == "main" else 5):
        parser.error("Seed count out of range")
    ledger = Ledger(settings.runs / "spending.sqlite3", settings.total_cap)
    # One runner process at a time; its requests/episodes are concurrent internally.
    with (settings.runs / "runner.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error("Another runner is active; do not launch a duplicate")
        try:
            return 0 if asyncio.run(execute(args, settings, ledger)) else 1
        except (ModelFailure, ValueError) as exc:
            # These are our own credential-safe exceptions.
            print(f"Stopped: {exc}")
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
