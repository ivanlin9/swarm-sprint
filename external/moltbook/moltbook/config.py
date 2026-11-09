"""Simulation constants and model backends.

API keys are read from the environment only -- never hard-code them here.
Copy .env.example to .env and fill it in, or export the variables directly.
"""
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# --------------------------------------------------------------------------- #
# Society
# --------------------------------------------------------------------------- #
NUM_AGENTS = 7          # 6 defenders + 1 attacker (the attacker is 14% of the society)
TOTAL_ROUNDS = 5        # rounds of deliberation before the final verdict is read
ATTACK_ROUND = 3        # first round in which the attacker injects the poisoned claim

VERDICTS = ["Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"]

SCENARIO_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "moltbook_scenarios_40.json",
)

# --------------------------------------------------------------------------- #
# Model backends
# --------------------------------------------------------------------------- #
# Exact model snapshots used in the paper. Providers retire snapshots over time;
# if a call 404s, substitute the nearest available version and say so when
# reporting results, since the numbers are snapshot-dependent.
MODEL_GPT5_MINI = "gpt-5-mini-2025-08-07"
MODEL_O4_MINI = "o4-mini"
MODEL_CLAUDE = "claude-haiku-4-5"
MODEL_GEMINI = "gemini-3.1-flash-lite"

BACKEND_GPT5_MINI = {"provider": "openai", "model": MODEL_GPT5_MINI}
BACKEND_O4_MINI = {"provider": "openai", "model": MODEL_O4_MINI}
BACKEND_CLAUDE = {"provider": "anthropic", "model": MODEL_CLAUDE}
BACKEND_GEMINI = {"provider": "google", "model": MODEL_GEMINI}

BACKENDS = {
    "gpt-5-mini": BACKEND_GPT5_MINI,
    "o4-mini": BACKEND_O4_MINI,
    "claude-4.5-haiku": BACKEND_CLAUDE,
    "gemini-3.1-flash-lite": BACKEND_GEMINI,
}

ENV_KEY = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
}


def require_key(provider: str) -> str:
    var = ENV_KEY[provider]
    key = os.getenv(var)
    if not key:
        raise RuntimeError(
            f"{var} is not set. Export it or put it in a .env file "
            f"(see .env.example). Keys are never read from source."
        )
    return key


# --------------------------------------------------------------------------- #
# Experiment configuration
# --------------------------------------------------------------------------- #
@dataclass
class SimulationConfig:
    """One experimental condition.

    Every experiment in the paper is this dataclass with different fields set;
    see experiments/ for the exact configuration behind each reported number.
    """

    name: str
    output: str

    num_agents: int = NUM_AGENTS
    total_rounds: int = TOTAL_ROUNDS
    attack_round: int = ATTACK_ROUND

    # "none" (Exp 1), "scripted" (Exp 2-7), "adaptive" (Exp 8)
    attacker: str = "scripted"
    # Lineage-tagging Verifier Module in front of the public log (Exp 6, Exp 8)
    verifier: bool = False
    # "fully" (Exp 1-4, 6, 8), "star" (Exp 5), "ring"/"sparse" (Section 5.3)
    topology: str = "fully"
    topology_seed: int = 42

    # Backend for every agent unless overridden per agent id below.
    backend: Dict[str, str] = field(default_factory=lambda: dict(BACKEND_GPT5_MINI))
    # e.g. {"Agent_A": BACKEND_CLAUDE} for the Config A heterogeneous society
    agent_backends: Dict[str, Dict[str, str]] = field(default_factory=dict)
    verifier_backend: Optional[Dict[str, str]] = None

    scenario_file: str = SCENARIO_FILE
    scenario_indices: Optional[List[int]] = None  # None = all 40
    seed: int = 42                                # speaking-order shuffle

    def backend_for(self, agent_id: str) -> Dict[str, str]:
        return self.agent_backends.get(agent_id, self.backend)
