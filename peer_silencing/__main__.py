from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from dotenv import dotenv_values

from .analysis import calibration, render
from .engine import execute
from .model import OfflineClient, PaidClient, SharedLedger, StopRun, ledger_snapshot
from .protocol import ROOT, load_manifest, prepare
from .storage import IntegrityError, digest, exclusive_run, immutable, read, seal, unseal

POLICY = ROOT / "configs/peer_execution_policy.json"
LEDGER = ROOT / "runs/spending.sqlite3"


def paid_gate(directory: Path, manifest: dict) -> tuple[dict, dict, dict | None]:
    policy = read(POLICY)
    if not policy["paid_enabled"] or digest(manifest) not in policy["approved_manifest_hashes"]:
        raise IntegrityError("Paid execution disabled or this exact manifest is not approved")
    if manifest["mode"] != "paid":
        raise IntegrityError("An offline manifest can never be used for a paid run")
    if (
        not 0 < policy["cumulative_testing_cap_usd"] <= 12
        or not 0 < policy["routine_total_cap_usd"] <= 45
    ):
        raise IntegrityError("Unsupported budget policy")
    snapshot = ledger_snapshot(LEDGER)
    if snapshot["unresolved"]:
        raise IntegrityError("Reconcile unresolved project calls before another paid launch")
    values = dotenv_values(ROOT / ".env", interpolate=False)
    if (
        values.get("ALLOW_PAID_API_CALLS") != "true"
        or not (values.get("OPENAI_API_KEY") or "").strip()
    ):
        raise IntegrityError("Project .env paid gate is disabled or key is missing")
    forecast = None
    if manifest["stage"] == "main":
        if not policy["main_enabled"] or not policy["main_calibration_run"]:
            raise IntegrityError("Main requires explicit approval and paid-smoke calibration")
        forecast = calibration(Path(policy["main_calibration_run"]).resolve(), manifest)
        if (
            snapshot["accounted_usd"] + forecast["projected_main_usd"]
            > policy["routine_total_cap_usd"]
        ):
            raise IntegrityError("Calibrated main manifest exceeds routine allowance")
        if (
            snapshot["accounted_usd"] + forecast["four_request_reservation_headroom_usd"]
            > policy["routine_total_cap_usd"]
        ):
            raise IntegrityError("Insufficient concurrent reservation headroom")
        remaining = (
            datetime.fromisoformat(manifest["data_collection_cutoff_utc"]) - datetime.now(UTC)
        ).total_seconds()
        if forecast["serial_duration_seconds"] > remaining:
            raise IntegrityError("Conservative serial-duration forecast exceeds collection window")
    if datetime.now(UTC) >= datetime.fromisoformat(manifest["data_collection_cutoff_utc"]):
        raise IntegrityError("Data-collection cutoff passed")
    return policy, values, forecast


async def run(directory: Path, paid: bool):
    with exclusive_run(directory):
        manifest = load_manifest(directory)
        if paid != (manifest["mode"] == "paid"):
            raise IntegrityError("Execution flag and manifest mode differ")
        block_gate = None
        if paid:
            policy, values, forecast = paid_gate(directory, manifest)
            ledger = SharedLedger(
                LEDGER, policy["cumulative_testing_cap_usd"], policy["routine_total_cap_usd"]
            )
            client = PaidClient(
                values["OPENAI_API_KEY"],
                ledger,
                "pilot" if manifest["stage"] == "smoke" else "peer_main",
                values.get("OPENAI_ORG_ID") or None,
                values.get("OPENAI_PROJECT_ID") or None,
            )

            def block_gate(number, block):
                current = ledger_snapshot(LEDGER)
                if (
                    forecast
                    and current["accounted_usd"] + forecast["projected_block_usd"]
                    > policy["routine_total_cap_usd"]
                ):
                    raise StopRun("Insufficient calibrated headroom for another balanced block")

            launch = directory / "launch_policy.json"
            if launch.exists():
                if unseal(launch)["policy"] != policy:
                    raise IntegrityError("Resume policy changed; audit required")
            else:
                immutable(
                    launch,
                    seal(
                        {
                            "policy": policy,
                            "budget_before": ledger_snapshot(LEDGER),
                            "forecast": forecast,
                        }
                    ),
                )
        else:
            client = OfflineClient()
        try:
            await execute(directory, manifest, client, block_gate)
        finally:
            await client.close()
        print(f"Completed {manifest['mode']} run. Analysis: {render(directory)}")


def main():
    parser = argparse.ArgumentParser(description="Peer-silencing pipeline (offline by default)")
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare", help="Freeze manifest; never calls a model")
    prep.add_argument("--stage", choices=["smoke", "main"], required=True)
    prep.add_argument("--mode", choices=["offline", "paid"], default="offline")
    prep.add_argument("--output", type=Path, required=True)
    run_parser = commands.add_parser("run")
    run_parser.add_argument("--run", type=Path, required=True)
    run_parser.add_argument("--paid", action="store_true")
    analysis = commands.add_parser("analyze")
    analysis.add_argument("--run", type=Path, required=True)
    preflight = commands.add_parser("preflight", help="Read-only manifest/budget report")
    preflight.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare(args.output.resolve(), args.stage, args.mode)
        print(
            json.dumps(
                {
                    "manifest_sha256": digest(result),
                    "mode": result["mode"],
                    "nominal_calls": result["nominal_calls"],
                    "scenario_ids": result["scenario_ids"],
                },
                indent=2,
            )
        )
    elif args.command == "run":
        asyncio.run(run(args.run.resolve(), args.paid))
    elif args.command == "analyze":
        print(render(args.run.resolve()))
    else:
        value = load_manifest(args.run.resolve())
        print(
            json.dumps(
                {
                    "manifest_sha256": digest(value),
                    "stage": value["stage"],
                    "mode": value["mode"],
                    "nominal_calls": value["nominal_calls"],
                    "shared_budget": ledger_snapshot(LEDGER),
                    "policy": read(POLICY),
                    "warning": "No calls made. Counts are not a cost/availability guarantee.",
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    try:
        main()
    except (IntegrityError, StopRun) as exc:
        raise SystemExit(str(exc)) from None
