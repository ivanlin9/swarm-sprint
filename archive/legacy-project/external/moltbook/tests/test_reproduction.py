#!/usr/bin/env python3
"""Check that moltbook.metrics reproduces the figures reported in the paper.

Point the script at the published result files and it recomputes every headline
number from scratch:

    python tests/test_reproduction.py --results /path/to/published/results

Without result files the script skips the comparison and runs only the offline
engine test (tests/test_offline.py covers that separately).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from moltbook.config import SCENARIO_FILE                # noqa: E402
from moltbook.metrics import compute, verifier_profile   # noqa: E402

TOL = 0.05  # the paper rounds to two decimals

# (label, filename, total_rounds, attack_round, expected metrics)
CONDITIONS = [
    ("Exp 2 attack", "experiment_2_attack_results_gpt.json", 5, 3,
     {"accuracy": 52.50, "sfr": 47.49, "infection": 3.33,
      "paralysis": 44.17, "rcr": 47.49, "ocr": 98.33}),
    ("Exp 3 seven rounds", "experiment_3_r7_results_gpt.json", 7, 3,
     {"accuracy": 52.09, "sfr": 47.92, "paralysis": 47.92, "rcr": 48.34}),
    # Exp 4 drops the two build-up rounds, so it runs three rounds, not five.
    ("Exp 4 no pre-trust", "experiment_4_notrust_results_gpt.json", 3, 1,
     {"accuracy": 56.26, "sfr": 43.75, "rcr": 43.74, "ocr": 98.74}),
    ("Exp 5 star", "experiment_5_isolation_results_gpt.json", 5, 3,
     {"accuracy": 61.67, "sfr": 38.34, "rcr": 43.74, "ocr": 92.50}),
    ("Exp 6 defense", "experiment_6_defense_results_gpt.json", 5, 3,
     {"accuracy": 85.83, "sfr": 14.17, "infection": 0.00,
      "rcr": 14.17, "dfr": 11.97, "ocr": 99.16}),
    ("Exp 8 adaptive", "experiment_8_adaptive_results.json", 5, 3,
     {"accuracy": 92.50, "sfr": 7.50, "infection": 0.00, "dfr": 2.63}),
]

# Table 7, computed from the Exp 6 transcripts.
VERIFIER_EXPECTED = {"calls": 1400, "flags": 273, "flag_rate": 19.5,
                     "recall": 100.0, "fpr": 11.95, "precision": 44.0}


def find(root: str, filename: str):
    for dirpath, _, files in os.walk(root):
        if filename in files:
            return os.path.join(dirpath, filename)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True,
                    help="directory containing the published result JSON files")
    ap.add_argument("--scenarios", default=SCENARIO_FILE)
    args = ap.parse_args()

    scenarios = json.load(open(args.scenarios, encoding="utf-8"))
    failures = skipped = 0

    for label, filename, rounds, attack, expected in CONDITIONS:
        path = find(args.results, filename)
        if not path:
            print(f"SKIP {label}: {filename} not found")
            skipped += 1
            continue
        got = compute(json.load(open(path, encoding="utf-8")),
                      scenarios, rounds, attack)
        for key, want in expected.items():
            ok = abs(got[key] - want) < TOL
            failures += not ok
            print(f"{'ok  ' if ok else 'FAIL'} {label:22s} {key.upper():10s} "
                  f"paper={want:7.2f}  recomputed={got[key]:7.2f}")

    path = find(args.results, "experiment_6_defense_results_gpt.json")
    if path:
        got = verifier_profile(json.load(open(path, encoding="utf-8")))
        for key, want in VERIFIER_EXPECTED.items():
            ok = abs(got[key] - want) < TOL
            failures += not ok
            print(f"{'ok  ' if ok else 'FAIL'} {'Verifier (Table 7)':22s} "
                  f"{key.upper():10s} paper={want:7.2f}  recomputed={got[key]:7.2f}")

    print(f"\n{failures} mismatch(es), {skipped} condition(s) skipped")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
