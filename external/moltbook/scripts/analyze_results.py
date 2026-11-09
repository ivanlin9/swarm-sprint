#!/usr/bin/env python3
"""Compute the paper's metrics from saved result files.

    python scripts/analyze_results.py results/exp2_attack.json
    python scripts/analyze_results.py results/*.json --rounds 7
    python scripts/analyze_results.py results/exp6_defense.json --verifier

Files matching *_trial*.json for the same experiment are pooled, and the mean
and standard deviation across trials are reported alongside the pooled figure.
"""
import argparse
import glob
import json
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from moltbook.config import SCENARIO_FILE            # noqa: E402
from moltbook.metrics import compute, verifier_profile  # noqa: E402

TRIAL_RE = re.compile(r"_trial\d+$")


def load(path: str) -> list:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def group(paths):
    """Group result files by experiment stem, so trials of one condition pool."""
    groups = {}
    for path in paths:
        stem = TRIAL_RE.sub("", os.path.splitext(os.path.basename(path))[0])
        groups.setdefault(stem, []).append(path)
    return groups


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--attack-round", type=int, default=3)
    ap.add_argument("--scenarios", default=SCENARIO_FILE,
                    help="scenario file, used for accurate RCR keywords")
    ap.add_argument("--verifier", action="store_true",
                    help="also report the Verifier detection profile (Table 7)")
    args = ap.parse_args()

    expanded = []
    for pattern in args.paths:
        expanded.extend(sorted(glob.glob(pattern)) or [pattern])

    scenarios = load(args.scenarios) if os.path.exists(args.scenarios) else None

    for stem, paths in sorted(group(expanded).items()):
        per_trial = [compute(load(p), scenarios, args.rounds, args.attack_round)
                     for p in sorted(paths)]
        pooled = compute([r for p in sorted(paths) for r in load(p)],
                         scenarios, args.rounds, args.attack_round)

        print(f"\n=== {stem}  ({len(paths)} file{'s' if len(paths) > 1 else ''}, "
              f"n={pooled['n']} defender-scenario observations) ===")
        for key in ("accuracy", "sfr", "infection", "paralysis", "rcr", "ocr", "dfr"):
            values = [t[key] for t in per_trial]
            line = f"  {key.upper():<10} {pooled[key]:6.2f}%"
            if len(values) > 1:
                line += (f"   across trials: {statistics.mean(values):6.2f}"
                         f" +/- {statistics.stdev(values):.2f}")
            print(line)
        print(f"  {'MTTF':<10} {pooled['mttf']:6.2f} rounds")

        if args.verifier:
            v = verifier_profile([r for p in sorted(paths) for r in load(p)],
                                 args.attack_round)
            print(f"  --- Verifier: {v['calls']:.0f} calls, {v['flags']:.0f} flags "
                  f"({v['flag_rate']:.1f}%)")
            print(f"      recall {v['recall']:.1f}%   FPR {v['fpr']:.2f}%   "
                  f"precision {v['precision']:.1f}%")


if __name__ == "__main__":
    main()
