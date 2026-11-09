"""Exp 4 -- No pre-trust: the poison is injected in round 1.

Removes the attacker's reputation-building phase to test whether accumulated
social capital is a prerequisite for the collapse. Note that the p-value for
Exp 2 vs Exp 4 is borderline at five trials; see Section 5.1.

The two build-up rounds are dropped rather than replaced, so this condition runs
three rounds, not five. Post-injection deliberation is therefore the same length
as in Exp 2 (rounds 3-5 there, rounds 1-3 here) and the two are comparable.
"""
from _common import parse_args, run_trials
from moltbook import SimulationConfig


def config():
    return SimulationConfig(
        name="Exp 4: No pre-trust",
        output="",
        attacker="scripted",
        verifier=False,
        topology="fully",
        attack_round=1,        # inject immediately, with no trust accrued
        total_rounds=3,        # 5 rounds minus the 2 removed build-up rounds
    )


if __name__ == "__main__":
    run_trials(config, parse_args(__doc__), "exp4_no_pretrust")
