"""Exp 8 -- Adaptive attacker against the unchanged Exp 6 defense.

The Verifier is identical to Exp 6; only the attacker adapts. It is told the
Verifier's rules, sees the verdict on its own previous message, and escalates
through stage = min(1 + times_flagged, 3).
"""
from _common import parse_args, run_trials
from moltbook import SimulationConfig


def config():
    return SimulationConfig(
        name="Exp 8: Fixed defense vs. adaptive attacker",
        output="",
        attacker="adaptive",
        verifier=True,
        topology="fully",
    )


if __name__ == "__main__":
    run_trials(config, parse_args(__doc__), "exp8_adaptive")
