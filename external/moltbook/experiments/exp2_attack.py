"""Exp 2 -- Main attack: one scripted attacker among six defenders.

The attacker holds 14% of the seats, builds trust for two rounds, then injects
the scenario's poison message. No defense.
"""
from _common import parse_args, run_trials
from moltbook import SimulationConfig


def config():
    return SimulationConfig(
        name="Exp 2: Attack (no defense)",
        output="",
        attacker="scripted",
        verifier=False,
        topology="fully",
    )


if __name__ == "__main__":
    run_trials(config, parse_args(__doc__), "exp2_attack")
