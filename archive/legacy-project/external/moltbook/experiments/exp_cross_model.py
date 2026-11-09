"""Section 4.4 -- cross-model replication of Exp 1 and Exp 2.

Runs the baseline and the attack on a homogeneous society of each model family
in turn, to show the collapse is structural rather than an artifact of one
provider's safety pipeline.

Note that o4-mini also generated the scenario set, so its numbers carry a
generator-evaluator confound and are an upper bound conditioned on that
generator (Section 7).
"""
import sys

from _common import parse_args, run_trials
from moltbook import SimulationConfig
from moltbook.config import BACKENDS


def build(model_key: str, attacked: bool):
    def make():
        return SimulationConfig(
            name=f"{model_key}: {'Exp 2 attack' if attacked else 'Exp 1 baseline'}",
            output="",
            attacker="scripted" if attacked else "none",
            num_agents=7,
            verifier=False,
            topology="fully",
            backend=dict(BACKENDS[model_key]),
        )
    return make


if __name__ == "__main__":
    args = parse_args(__doc__)
    models = [m for m in sys.argv[1:] if m in BACKENDS] or list(BACKENDS)
    for model_key in models:
        slug = model_key.replace(".", "").replace("-", "_")
        for attacked in (False, True):
            stem = f"exp{'2_attack' if attacked else '1_baseline'}_{slug}"
            run_trials(build(model_key, attacked), args, stem)
