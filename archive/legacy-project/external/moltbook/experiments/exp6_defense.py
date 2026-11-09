"""Exp 6 -- System defense: Exp 2 with lenient data lineage verification.

Every message, from defenders and attacker alike, is checked against the
official record; claims that cannot be traced there keep their place in the
transcript but carry a visible lineage warning.
"""
from _common import parse_args, run_trials
from moltbook import SimulationConfig


def config():
    return SimulationConfig(
        name="Exp 6: System defense (lineage tagging)",
        output="",
        attacker="scripted",
        verifier=True,
        topology="fully",
    )


if __name__ == "__main__":
    run_trials(config, parse_args(__doc__), "exp6_defense")
