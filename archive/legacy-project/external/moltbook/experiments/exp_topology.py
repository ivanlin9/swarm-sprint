"""Section 5.3 -- topology sweep: ring and sparse (star is Exp 5, fully is Exp 2).

Tests whether the collapse depends on the fully-connected communication pattern.
It does not: every constrained topology recovers partially, and the degree of
recovery tracks how much residual peer exposure remains.
"""
import sys

from _common import RESULTS_DIR, parse_args, run_trials
from moltbook import SimulationConfig

TOPOLOGIES = ["ring", "sparse", "star", "fully"]


def config_for(topology: str):
    def build():
        return SimulationConfig(
            name=f"Topology: {topology}",
            output="",
            attacker="scripted",
            verifier=False,
            topology=topology,
        )
    return build


if __name__ == "__main__":
    args = parse_args(__doc__)
    requested = [t for t in sys.argv[1:] if t in TOPOLOGIES] or ["ring", "sparse"]
    for topo in requested:
        run_trials(config_for(topo), args, f"exp_topology_{topo}")
