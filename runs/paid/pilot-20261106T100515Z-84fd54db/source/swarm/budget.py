"""Persistent, cross-process reservations. Uncertain requests retain their reservation.

The ledger covers ONLY this runner, not other API use, taxes or price changes.
Input reserve uses a byte upper bound plus 4096 serialization tokens; accounting
uses the documented highest standard cache-write price ($5/M) conservatively.
No automatic retry can bypass reservation or turn an unknown request into free spend.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

INPUT_RATE = 2.0
CACHED_RATE = 0.10
INPUT_CEILING = 5.0
OUTPUT_RATE = 10.0
MARGIN = 1.10


class BudgetExceeded(RuntimeError):
    pass


class Ledger:
    def __init__(self, path: Path, total_cap: float = 50):
        if not 0 < total_cap <= 50:
            raise ValueError("Invalid total cap")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path, self.total_cap = path, total_cap
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS calls (
                    id TEXT PRIMARY KEY, stage TEXT NOT NULL, label TEXT NOT NULL,
                    status TEXT NOT NULL, reserved REAL NOT NULL,
                    accounted REAL, estimate REAL, input_tokens INTEGER,
                    output_tokens INTEGER, cached_tokens INTEGER, response_id TEXT,
                    created TEXT DEFAULT CURRENT_TIMESTAMP
                );
            """)

    def connect(self):
        return sqlite3.connect(self.path, timeout=30)

    @staticmethod
    def reserve_amount(payload: dict, max_output: int) -> float:
        # UTF-8 bytes upper-bound byte-BPE tokens; add ample request framing allowance.
        n = len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) + 4096
        return MARGIN * (n * INPUT_CEILING + max_output * OUTPUT_RATE) / 1e6

    def reserve(self, stage: str, label: str, amount: float, stage_cap: float) -> str:
        if not 0 < amount < float("inf") or not 0 < stage_cap <= 50:
            raise ValueError("Invalid reservation")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            total = db.execute(
                "SELECT COALESCE(SUM(COALESCE(accounted,reserved)),0) FROM calls"
            ).fetchone()[0]
            subtotal = db.execute(
                "SELECT COALESCE(SUM(COALESCE(accounted,reserved)),0) FROM calls WHERE stage=?",
                (stage,),
            ).fetchone()[0]
            if total + amount > self.total_cap or subtotal + amount > stage_cap:
                raise BudgetExceeded(
                    f"Budget would be exceeded: total={total:.4f}, stage={subtotal:.4f}, next_reserve={amount:.4f}"
                )
            call_id = uuid.uuid4().hex
            db.execute(
                "INSERT INTO calls(id,stage,label,status,reserved) VALUES (?,?,?,?,?)",
                (call_id, stage, label, "reserved", amount),
            )
        return call_id

    def complete(self, call_id: str, usage: dict, response_id: str):
        n_in, n_out = usage["input_tokens"], usage["output_tokens"]
        cached = (usage.get("input_tokens_details") or {}).get("cached_tokens", 0)
        if not (
            isinstance(n_in, int)
            and isinstance(n_out, int)
            and isinstance(cached, int)
            and 0 <= cached <= n_in
            and n_out >= 0
        ):
            raise ValueError("Invalid usage; reservation retained")
        estimate = ((n_in - cached) * INPUT_RATE + cached * CACHED_RATE + n_out * OUTPUT_RATE) / 1e6
        accounted = MARGIN * (n_in * INPUT_CEILING + n_out * OUTPUT_RATE) / 1e6
        with self.connect() as db:
            row = db.execute("SELECT reserved,status FROM calls WHERE id=?", (call_id,)).fetchone()
            if row is None or row[1] != "reserved":
                raise ValueError("Missing/already-settled reservation")
            db.execute(
                "UPDATE calls SET status='complete',accounted=?,estimate=?,input_tokens=?,output_tokens=?,cached_tokens=?,response_id=? WHERE id=?",
                (accounted, estimate, n_in, n_out, cached, response_id, call_id),
            )
        if accounted > row[0]:
            raise RuntimeError("Usage exceeded conservative reservation; stop and review pricing")

    def uncertain(self, call_id: str):
        with self.connect() as db:
            db.execute(
                "UPDATE calls SET status='uncertain' WHERE id=? AND status='reserved'", (call_id,)
            )

    def summary(self) -> dict:
        with self.connect() as db:
            rows = db.execute(
                "SELECT stage,COUNT(*),SUM(COALESCE(accounted,reserved)),SUM(COALESCE(estimate,0)),SUM(status!='complete') FROM calls GROUP BY stage"
            ).fetchall()
        return {
            "total_cap_usd": self.total_cap,
            "stages": {
                stage: {
                    "calls": count,
                    "accounted_or_reserved_usd": cost,
                    "standard_token_estimate_usd": estimate,
                    "unresolved_calls": uncertain,
                }
                for stage, count, cost, estimate, uncertain in rows
            },
        }
