"""Exp 1 -- Baseline: seven defenders, no attacker.

Establishes what the society achieves on this scenario set with nothing
adversarial present. The residual Hold rate here is intrinsic scenario
ambiguity; it is the reference point for every attacked condition, not a
ceiling (Exp 8 exceeds it).
"""
from _common import parse_args, run_trials
from moltbook import SimulationConfig


def config():
    return SimulationConfig(
        name="Exp 1: Baseline (no attack)",
        output="",
        attacker="none",
        num_agents=7,          # all seven are defenders here
        verifier=False,
        topology="fully",
    )


if __name__ == "__main__":
    run_trials(config, parse_args(__doc__), "exp1_baseline")
