"""Section 5.3 -- heterogeneous societies.

Config A varies the attacker's model family (Claude attacker, GPT-5-mini
defenders). Config B mixes defender families so no single backbone can explain
the outcome. Both need the corresponding provider keys to be set.
"""
import sys

from _common import parse_args, run_trials
from moltbook import SimulationConfig
from moltbook.config import BACKEND_CLAUDE, BACKEND_GEMINI, BACKEND_GPT5_MINI, BACKEND_O4_MINI


def config_a():
    """Claude-driven attacker against a GPT-5-mini defender population."""
    return SimulationConfig(
        name="Config A: Claude attacker",
        output="",
        attacker="scripted",
        verifier=False,
        topology="fully",
        backend=dict(BACKEND_GPT5_MINI),
        agent_backends={"Agent_A": dict(BACKEND_CLAUDE)},
    )


def config_b():
    """Mixed defender families; the attacker stays on GPT-5-mini."""
    return SimulationConfig(
        name="Config B: Mixed society",
        output="",
        attacker="scripted",
        verifier=False,
        topology="fully",
        backend=dict(BACKEND_GPT5_MINI),
        agent_backends={
            "Agent_D1": dict(BACKEND_GPT5_MINI),
            "Agent_D2": dict(BACKEND_GPT5_MINI),
            "Agent_D3": dict(BACKEND_GEMINI),
            "Agent_D4": dict(BACKEND_GEMINI),
            "Agent_D5": dict(BACKEND_O4_MINI),
            "Agent_D6": dict(BACKEND_O4_MINI),
        },
    )


CONFIGS = {"a": (config_a, "exp_hetero_A"), "b": (config_b, "exp_hetero_B")}

if __name__ == "__main__":
    args = parse_args(__doc__)
    requested = [c for c in sys.argv[1:] if c.lower() in CONFIGS] or ["a", "b"]
    for name in requested:
        build, stem = CONFIGS[name.lower()]
        run_trials(build, args, stem)
