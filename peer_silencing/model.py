from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI

from swarm.budget import BudgetExceeded, Ledger

from .protocol import MODEL, SCHEMA, validate_output
from .storage import IntegrityError, digest, immutable, seal, unseal


class TurnFailure(RuntimeError):
    """Terminal scientific output failure. Never contains SDK bodies or credentials."""


class StopRun(RuntimeError):
    """Budget, uncertain transport, or accounting failure: stop new dispatch."""


def ledger_snapshot(path: Path) -> dict:
    if not path.exists():
        return {"calls": 0, "accounted_usd": 0.0, "testing_usd": 0.0, "unresolved": 0}
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        count, total, testing, unresolved = db.execute(
            "SELECT COUNT(*),COALESCE(SUM(COALESCE(accounted,reserved)),0),"
            "COALESCE(SUM(CASE WHEN stage!='peer_main' THEN COALESCE(accounted,reserved) "
            "ELSE 0 END),0),COALESCE(SUM(status IN ('reserved','uncertain')),0) FROM calls"
        ).fetchone()
    return {
        "calls": count,
        "accounted_usd": total,
        "testing_usd": testing,
        "unresolved": unresolved,
    }


class SharedLedger(Ledger):
    """Same calls table as the old runner; never reset prior charges."""

    def __init__(self, path: Path, testing_cap=5.0, total_cap=45.0):
        if not 0 < testing_cap <= 12 or not 0 < total_cap <= 45:
            raise ValueError("Unsupported execution allowance")
        super().__init__(path, total_cap)
        self.testing_cap = testing_cap

    def reserve_call(self, stage: str, label: str, payload: dict) -> str:
        import uuid

        if stage not in {"pilot", "peer_main"}:
            raise ValueError("Unknown spending stage")
        amount = self.reserve_amount(payload, MODEL["max_output_tokens"])
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            total, testing = db.execute(
                "SELECT COALESCE(SUM(COALESCE(accounted,reserved)),0),"
                "COALESCE(SUM(CASE WHEN stage!='peer_main' THEN COALESCE(accounted,reserved) "
                "ELSE 0 END),0) FROM calls"
            ).fetchone()
            if total + amount > self.total_cap or (
                stage == "pilot" and testing + amount > self.testing_cap
            ):
                raise BudgetExceeded("Shared cumulative allowance cannot reserve this request")
            call_id = uuid.uuid4().hex
            db.execute(
                "INSERT INTO calls(id,stage,label,status,reserved) VALUES (?,?,?,?,?)",
                (call_id, stage, label, "reserved", amount),
            )
        return call_id

    def settle(self, call_id: str, usage: dict, response_id: str):
        n_in, n_out = usage.get("input_tokens"), usage.get("output_tokens")
        details = usage.get("input_tokens_details") or {}
        cached = details.get("cached_tokens", 0)
        if not all(type(x) is int and x >= 0 for x in (n_in, n_out, cached)) or cached > n_in:
            raise StopRun("Invalid usage; retain reservation")
        accounted = 1.10 * (n_in * 5.0 + n_out * 10.0) / 1e6
        # An exact nominal estimate requires complete cache-category information.
        estimate = None
        written = details.get("cache_write_tokens")
        if written is not None:
            if type(written) is not int or written < 0 or written + cached > n_in:
                raise StopRun("Invalid cache usage; retain reservation")
            ttl = details.get("cache_write_tokens_details") or {}
            short, long = ttl.get("ttl_30m_tokens", 0), ttl.get("ttl_12h_tokens", 0)
            if not all(type(x) is int and x >= 0 for x in (short, long)):
                raise StopRun("Invalid cache lifetime usage")
            if short + long == written:
                estimate = (
                    (n_in - cached - written) * 2
                    + cached * 0.1
                    + short * 2.5
                    + long * 5
                    + n_out * 10
                ) / 1e6
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT status,reserved,accounted,response_id FROM calls WHERE id=?", (call_id,)
            ).fetchone()
            if row is None:
                raise StopRun("Missing reservation")
            if row[0] == "complete":
                if row[2] != accounted or row[3] != response_id:
                    raise IntegrityError("Conflicting settlement")
                if accounted > row[1]:
                    raise StopRun("Previously settled usage exceeded reservation; audit required")
                return
            if row[0] not in {"reserved", "uncertain"}:
                raise StopRun("Unexpected ledger state")
            db.execute(
                "UPDATE calls SET status='complete',accounted=?,estimate=?,input_tokens=?,"
                "output_tokens=?,cached_tokens=?,response_id=? WHERE id=?",
                (accounted, estimate, n_in, n_out, cached, response_id, call_id),
            )
        if accounted > row[1]:
            raise StopRun("Actual usage exceeded reservation; stop for audit")


def request_payload(system: str, user: str) -> dict:
    return {
        **MODEL,
        "input": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "analyst_turn",
                "schema": SCHEMA,
                "strict": True,
            }
        },
        "truncation": "disabled",
    }


def parse_response(raw: dict) -> dict:
    if raw.get("status") != "completed":
        raise TurnFailure("Incomplete model output")
    chunks = []
    for item in raw.get("output", []):
        if item.get("type") != "message":
            continue
        for part in item.get("content", []):
            if part.get("type") == "refusal":
                raise TurnFailure("Model refusal (not Hold)")
            if part.get("type") == "output_text":
                chunks.append(part["text"])
    try:
        return validate_output(json.loads("".join(chunks)))
    except (ValueError, TypeError, KeyError):
        raise TurnFailure("Invalid structured output (not Hold)") from None


class OfflineClient:
    """Deterministic plumbing fixture, NOT an experimental result or model forecast."""

    mode = "offline"

    def __init__(self):
        self.calls = 0
        self.stopped = False

    async def close(self):
        pass

    async def call(self, system, user, directory, metadata):
        directory.mkdir(parents=True, exist_ok=True)
        request = {"payload": request_payload(system, user), "metadata": metadata}
        immutable(directory / "request.json", seal(request))
        result_path = directory / "result.json"
        if result_path.exists():
            record = unseal(result_path)
            if record["request_hash"] != digest(request):
                raise IntegrityError("Offline request changed")
            return record["output"]
        self.calls += 1
        await asyncio.sleep(0)
        output = {
            "thought": "Offline fixture only.",
            "verdict": "Hold",
            "message": f"Offline fixture {digest(request)[:16]}; not an LLM result.",
        }
        immutable(
            result_path,
            seal({"mode": "offline", "request_hash": digest(request), "output": output}),
        )
        return output


class PaidClient:
    mode = "paid"

    def __init__(
        self,
        key: str,
        ledger: SharedLedger,
        stage: str,
        organization=None,
        project=None,
        transport=None,
        cutoff="2026-11-08T23:59:00+00:00",
    ):
        if not key.strip():
            raise ValueError("Missing API key")
        self.ledger, self.stage = ledger, stage
        self.cutoff = datetime.fromisoformat(cutoff)
        self.sem = asyncio.Semaphore(4)
        self.stopped = False
        self.client = transport or AsyncOpenAI(
            api_key=key,
            organization=organization,
            project=project,
            base_url="https://api.openai.com/v1",
            timeout=90,
            max_retries=0,
        )

    async def close(self):
        await self.client.close()

    async def call(self, system, user, directory, metadata):
        payload = request_payload(system, user)
        # The conservative ledger is calibrated to short-context Standard requests only.
        if len(json.dumps(payload).encode()) + 4096 > 200_000:
            raise StopRun("Input exceeds conservative short-context limit")
        request = {"payload": payload, "metadata": metadata}
        immutable(directory / "request.json", seal(request))
        key = digest(request)
        result_path = directory / "result.json"
        if result_path.exists():
            saved = unseal(result_path)
            if saved["request_hash"] != key or saved["mode"] != "paid":
                raise IntegrityError("Paid request/result mismatch")
            return validate_output(saved["output"])
        if (directory / "terminal.json").exists():
            raise TurnFailure("Previously terminal attempt; do not resample")
        async with self.sem:
            for attempt in range(2):
                intent_path = directory / f"attempt-{attempt}.intent.json"
                raw_path = directory / f"attempt-{attempt}.response.json"
                error_path = directory / f"attempt-{attempt}.error.json"
                if intent_path.exists():
                    intent = unseal(intent_path)
                    if intent["request_hash"] != key:
                        raise IntegrityError("Attempt request changed")
                    call_id = intent["call_id"]
                    if raw_path.exists():
                        record = unseal(raw_path)
                    elif error_path.exists() and unseal(error_path)["retryable"] and attempt == 0:
                        continue
                    else:
                        self.stopped = True
                        raise StopRun(
                            "Unresolved dispatched attempt; manual reconciliation required"
                        )
                else:
                    if self.stopped or datetime.now(UTC) >= self.cutoff:
                        raise StopRun("Dispatch stopped or data-collection cutoff reached")
                    try:
                        call_id = self.ledger.reserve_call(self.stage, key, payload)
                    except BudgetExceeded:
                        self.stopped = True
                        raise StopRun("Shared budget exhausted") from None
                    immutable(
                        intent_path,
                        seal(
                            {
                                "call_id": call_id,
                                "request_hash": key,
                                "dispatch_utc": datetime.now(UTC).isoformat(),
                            }
                        ),
                    )
                    start = time.monotonic()
                    try:
                        response = await self.client.responses.create(**payload)
                        record = {
                            "call_id": call_id,
                            "request_hash": key,
                            "response": response.model_dump(mode="json"),
                            "elapsed_seconds": time.monotonic() - start,
                            "received_utc": datetime.now(UTC).isoformat(),
                        }
                        immutable(raw_path, seal(record))
                    except BaseException as exc:
                        self.ledger.uncertain(call_id)
                        status = getattr(exc, "status_code", None)
                        retryable = status == 429 or (
                            isinstance(exc, APIConnectionError)
                            and not isinstance(exc, APITimeoutError)
                        )
                        immutable(
                            error_path,
                            seal(
                                {
                                    "call_id": call_id,
                                    "error_type": type(exc).__name__,
                                    "http_status": status,
                                    "retryable": retryable,
                                    "reservation_retained": True,
                                }
                            ),
                        )
                        if isinstance(exc, asyncio.CancelledError):
                            self.stopped = True
                            raise
                        if retryable and attempt == 0:
                            await asyncio.sleep(2)
                            continue
                        self.stopped = True
                        raise StopRun(
                            "Transport/service failure; see sanitized attempt log"
                        ) from None
                if record["call_id"] != call_id or record["request_hash"] != key:
                    raise IntegrityError("Response/attempt mismatch")
                raw = record["response"]
                try:
                    if not raw.get("usage") or not raw.get("id"):
                        raise StopRun("Missing usage/response ID; reservation retained")
                    self.ledger.settle(call_id, raw["usage"], raw["id"])
                    if raw.get("service_tier") not in {None, "default"}:
                        raise StopRun("Unexpected service tier; review pricing")
                except Exception:
                    self.stopped = True
                    self.ledger.uncertain(call_id)
                    raise
                try:
                    output = parse_response(raw)
                except TurnFailure as exc:
                    immutable(
                        directory / "terminal.json", seal({"reason": str(exc), "call_id": call_id})
                    )
                    raise
                immutable(
                    result_path,
                    seal(
                        {
                            "mode": "paid",
                            "request_hash": key,
                            "output": output,
                            "call_id": call_id,
                            "response_id": raw["id"],
                        }
                    ),
                )
                return output
        raise StopRun("Retry limit exhausted")
