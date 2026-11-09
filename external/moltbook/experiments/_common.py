"""Shared CLI plumbing for the experiment entry points."""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

RESULTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results"
)


def parse_args(description: str) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--trials", type=int, default=1,
                   help="repeat the whole scenario set N times "
                        "(the paper uses 5 for the GPT-5-mini main experiments)")
    p.add_argument("--limit", type=int, default=None,
                   help="run only the first N scenarios (smoke testing)")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--outdir", default=RESULTS_DIR)
    return p.parse_args()


def run_trials(build_config, args, stem: str):
    """Run `args.trials` repetitions, writing one result file per trial."""
    from moltbook import run

    indices = list(range(args.limit)) if args.limit else None
    for trial in range(1, args.trials + 1):
        suffix = "" if args.trials == 1 else f"_trial{trial}"
        cfg = build_config()
        cfg.output = os.path.join(args.outdir, f"{stem}{suffix}.json")
        cfg.scenario_indices = indices
        cfg.seed = args.seed + trial - 1
        run(cfg)
