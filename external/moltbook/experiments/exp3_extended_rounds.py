"""Exp 3 -- Round extension: Exp 2 run for seven rounds instead of five.

Tests the common assumption that longer debate lets a group self-correct. It
does not: the extra rounds let the attacker consolidate the false consensus.
"""
from _common import parse_args, run_trials
from moltbook import SimulationConfig


def config():
    return SimulationConfig(
        name="Exp 3: Round extension (7 rounds)",
        output="",
        attacker="scripted",
        verifier=False,
        topology="fully",
        total_rounds=7,
    )


if __name__ == "__main__":
    run_trials(config, parse_args(__doc__), "exp3_extended_rounds")
