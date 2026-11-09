"""One explicitly approved, bounded recovery operation; never runs continuations."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from pathlib import Path

from dotenv import dotenv_values

from peer_silencing.engine import segment
from peer_silencing.model import PaidClient, SharedLedger, StopRun, request_payload
from peer_silencing.protocol import FOCAL, ROOT, load_manifest, scenarios
from peer_silencing.storage import (
    IntegrityError,
    digest,
    exclusive_run,
    file_hash,
    immutable,
    read,
    seal,
    unseal,
)
from swarm.budget import BudgetExceeded

RUN = ROOT / "runs/peer_silencing/paid-smoke"
POLICY = ROOT / "configs/peer_execution_policy.json"
SCOPE = "a01-prefix-completion-20261107"
OLD_CALLS = {"55c16bf49b664dca82595b03c502e622", "3916956f8244487c9edb1d152c42f087"}
MANIFEST = "c51524cce5f85bfe3f0d07bdf6deebb38f4cf41cdd2903b6beee4f7b5a97943f"


class BoundedLedger(SharedLedger):
    # The entire operation holds the original run's exclusive lock. No await occurs
    # between this scope check and the parent's global transactional reservation.
    def reserve_call(self, stage, label, payload):
        with self.connect() as db:
            n, used = db.execute(
                "SELECT COUNT(*),COALESCE(SUM(COALESCE(accounted,reserved)),0) "
                "FROM calls WHERE label LIKE ?",
                (SCOPE + "|%",),
            ).fetchone()
        if stage != "pilot" or n >= 6 or used + self.reserve_amount(payload, 2048) > 1.0:
            raise BudgetExceeded("Six-attempt / $1 conservative operation ceiling reached")
        return super().reserve_call(stage, SCOPE + "|" + label, payload)


class PrefixOnlyClient:
    mode = "paid"

    def __init__(self, client):
        self.client = client

    async def call(self, system, user, directory, metadata):
        if (metadata["scenario"], metadata["exposure"], metadata["branch"], metadata["round"]) != (
            "A-01",
            "attack",
            "prefix",
            5,
        ) or metadata["agent"] not in FOCAL:
            raise IntegrityError("Outside approved six-turn scope")
        if directory.name == "r5-Agent_D2":
            old = unseal(directory / "attempt-0.error.json")
            if old["call_id"] not in OLD_CALLS or old["error_type"] != "CancelledError":
                raise IntegrityError("Only the user-cancelled attempt may be replaced")
            if (directory / "result.json").exists() or (
                directory / "attempt-0.response.json"
            ).exists():
                raise IntegrityError("Do not replace an already received response")
            expected = {"payload": request_payload(system, user), "metadata": metadata}
            if unseal(directory / "request.json") != expected:
                raise IntegrityError("Replacement scientific input differs")
            directory = directory.with_name("r5-Agent_D2-authorized-recovery")
        return await self.client.call(system, user, directory, metadata)


async def main(paid):
    if not paid:
        raise IntegrityError("Explicit --paid required")
    with exclusive_run(RUN):
        manifest = load_manifest(RUN)
        policy = read(POLICY)
        approval = policy.get("prefix_completion", {})
        if (
            digest(manifest) != MANIFEST
            or not approval.get("enabled")
            or approval.get("scope") != SCOPE
            or policy["paid_enabled"]
            or policy["main_enabled"]
        ):
            raise IntegrityError("Scoped approval missing or full-run gates unexpectedly enabled")
        if datetime.now(UTC) >= datetime.fromisoformat(manifest["data_collection_cutoff_utc"]):
            raise IntegrityError("Collection cutoff passed")
        values = dotenv_values(ROOT / ".env", interpolate=False)
        if values.get("ALLOW_PAID_API_CALLS") != "true" or not values.get("OPENAI_API_KEY"):
            raise IntegrityError("Credential/paid gate disabled")
        ledger = BoundedLedger(
            ROOT / "runs/spending.sqlite3",
            policy["cumulative_testing_cap_usd"],
            policy["routine_total_cap_usd"],
        )
        with ledger.connect() as db:
            unresolved = {
                row[0]
                for row in db.execute(
                    "SELECT id FROM calls WHERE status IN ('reserved','uncertain')"
                )
            }
        if unresolved != OLD_CALLS:
            raise IntegrityError("Unexpected unresolved calls; audit before dispatch")
        immutable(
            RUN / "prefix_completion_authorization.json",
            seal(
                {
                    "scope": SCOPE,
                    "manifest_hash": MANIFEST,
                    "driver_sha256": file_hash(Path(__file__)),
                    "max_new_attempts": 6,
                    "additional_conservative_cap_usd": 1.0,
                    "retained_uncertain_call_ids": sorted(OLD_CALLS),
                    "replacement": {
                        "old_turn": "r5-Agent_D2",
                        "new_call_directory": "r5-Agent_D2-authorized-recovery",
                    },
                    "reason": "User approved recommendation to finish only A-01 attacked prefix; no observed response resampled.",
                }
            ),
        )
        client = PaidClient(
            values["OPENAI_API_KEY"],
            ledger,
            "pilot",
            values.get("OPENAI_ORG_ID") or None,
            values.get("OPENAI_PROJECT_ID") or None,
        )
        try:
            result = await segment(
                RUN / "scenarios/A-01/attack/prefix",
                manifest,
                scenarios()["A-01"],
                "attack",
                "prefix",
                PrefixOnlyClient(client),
            )
        finally:
            await client.close()
        if result is None:
            raise StopRun("Prefix contains a terminal output failure; no further execution")
        print("A-01 attacked prefix complete. No clean turns or continuations dispatched.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paid", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(main(args.paid))
    except (IntegrityError, StopRun) as exc:
        raise SystemExit(str(exc)) from None
