"""Moltbook: a flat, peer-to-peer multi-agent deliberation testbed.

Reference implementation for "Data Poisoning in LLM Multi-Agent Societies:
Social Proof Drives Collective Decision Failure in Financial Deliberation"
(ETRI Journal, 2026).
"""
from .config import SimulationConfig
from .engine import run

__all__ = ["SimulationConfig", "run"]
__version__ = "1.0.0"
