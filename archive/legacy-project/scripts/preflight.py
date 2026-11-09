"""Local-only readiness checks. Never creates an API client or sends requests.

Run after the user has finished adding credentials:
    uv run --frozen python scripts/preflight.py
"""

from __future__ import annotations

import importlib.metadata
import json
import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    values = dotenv_values(ROOT / ".env", interpolate=False)
    failures: list[str] = []
    versions: dict[str, str] = {}
    for package in ("terrarium-agents", "openai", "python-dotenv", "PyYAML"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            failures.append(f"Missing dependency: {package}")

    paths = {
        "env_file": ROOT / ".env",
        "study_config": ROOT / "configs/study.yaml",
        "colosseum_source": ROOT / "external/colosseum/pyproject.toml",
        "collab_source": ROOT / "external/colosseum/external/CoLLAB",
    }
    for label, path in paths.items():
        if not path.exists():
            failures.append(f"Missing {label}")

    # Deliberately print only whether a key exists, never its contents or prefix.
    key_present = bool((values.get("OPENAI_API_KEY") or "").strip())
    if not key_present:
        failures.append("OPENAI_API_KEY is empty in .env")

    for name in (
        "SWARM_PILOT_BUDGET_USD",
        "SWARM_TOTAL_BUDGET_USD",
        "OPENAI_TIMEOUT_SECONDS",
        "OPENAI_MAX_OUTPUT_TOKENS",
    ):
        try:
            number = float(values.get(name) or "")
            if not 0 < number < float("inf"):
                raise ValueError
        except ValueError:
            failures.append(f"{name} must be a finite positive number")

    print(json.dumps({
        "workspace": str(ROOT),
        "python": sys.version.split()[0],
        "versions": versions,
        "key_present": key_present,
        "paid_calls_enabled": values.get("ALLOW_PAID_API_CALLS") == "true",
        "network_requests_made": 0,
        "failures": failures,
        "scope": "File/dependency readiness only; API access and testbed execution untested.",
    }, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
