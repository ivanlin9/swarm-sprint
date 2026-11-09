from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    # Never serialize this dataclass: credentials are intentionally excluded from repr.
    key: str = field(default="", repr=False)
    organization: str = field(default="", repr=False)
    project: str = field(default="", repr=False)
    model: str = "gpt-6.1-sol"
    effort: str = "low"
    paid: bool = False
    agents: int = 8
    rounds: int = 3
    message_chars: int = 600
    max_output: int = 2048
    timeout: float = 90
    episode_concurrency: int = 2
    request_concurrency: int = 4
    pilot_cap: float = 5
    total_cap: float = 50
    runs: Path = ROOT / "runs"

    @classmethod
    def load(cls) -> Settings:
        v = dotenv_values(ROOT / ".env", interpolate=False)
        study = yaml.safe_load((ROOT / "configs/study.yaml").read_text())
        s = cls(
            key=v.get("OPENAI_API_KEY") or "",
            organization=v.get("OPENAI_ORG_ID") or "",
            project=v.get("OPENAI_PROJECT_ID") or "",
            model=v.get("OPENAI_MODEL") or "gpt-6.1-sol",
            effort=v.get("OPENAI_REASONING_EFFORT") or "low",
            paid=v.get("ALLOW_PAID_API_CALLS") == "true",
            agents=int(v.get("SWARM_AGENTS") or 8),
            rounds=int(v.get("SWARM_DISCUSSION_ROUNDS") or 3),
            message_chars=int(v.get("SWARM_MAX_MESSAGE_CHARS") or 600),
            max_output=int(v.get("OPENAI_MAX_OUTPUT_TOKENS") or 2048),
            timeout=float(v.get("OPENAI_TIMEOUT_SECONDS") or 90),
            episode_concurrency=int(v.get("SWARM_MAX_CONCURRENT_EPISODES") or 2),
            request_concurrency=int(v.get("SWARM_MAX_CONCURRENT_REQUESTS") or 4),
            pilot_cap=float(v.get("SWARM_PILOT_BUDGET_USD") or 5),
            total_cap=float(v.get("SWARM_TOTAL_BUDGET_USD") or 50),
            runs=(ROOT / (v.get("SWARM_RUNS_DIR") or "runs")).resolve(),
        )
        if s.model != "gpt-6.1-sol":
            raise ValueError(
                "Model not price-validated. Add a reviewed price entry before switching."
            )
        if s.effort not in {"low", "medium", "high", "xhigh", "max"}:
            raise ValueError("Unsupported reasoning effort")
        if (
            s.agents != study["population"]["agents"]
            or s.rounds != study["communication"]["discussion_rounds"]
        ):
            raise ValueError(".env and study.yaml disagree on agents or rounds")
        if s.agents != 8 or s.rounds != 3 or s.message_chars != 600:
            raise ValueError(
                "This pilot protocol is fixed at eight agents, three rounds, 600 chars"
            )
        if not (math.isfinite(s.total_cap) and 0 < s.total_cap <= 50):
            raise ValueError("Total cap must be positive and at most USD 50")
        if not (math.isfinite(s.pilot_cap) and 0 < s.pilot_cap <= 5):
            raise ValueError("Pilot cap must be positive and at most USD 5")
        if not 256 <= s.max_output <= 8192 or not 0 < s.timeout <= 300:
            raise ValueError("Invalid output limit or timeout")
        if not 1 <= s.episode_concurrency <= 4 or not 1 <= s.request_concurrency <= 8:
            raise ValueError("Concurrency outside safe range")
        if s.runs != ROOT / "runs":
            raise ValueError("Keep the shared spending ledger in this project's runs/ directory")
        return s

    def public(self) -> dict:
        return {
            k: getattr(self, k)
            for k in (
                "model",
                "effort",
                "agents",
                "rounds",
                "message_chars",
                "max_output",
                "timeout",
                "episode_concurrency",
                "request_concurrency",
                "pilot_cap",
                "total_cap",
            )
        }
