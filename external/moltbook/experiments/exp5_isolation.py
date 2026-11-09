"""Exp 5 -- Social isolation: star topology.

Defenders see the attacker but not each other, so exposure to the poisoned
claim is unchanged while peer consensus pressure is removed. The recovery here
is what isolates social proof as the operative mechanism.
"""
from _common import parse_args, run_trials
from moltbook import SimulationConfig


def config():
    return SimulationConfig(
        name="Exp 5: Social isolation (star)",
        output="",
        attacker="scripted",
        verifier=False,
        topology="star",
    )


if __name__ == "__main__":
    run_trials(config, parse_args(__doc__), "exp5_isolation")
