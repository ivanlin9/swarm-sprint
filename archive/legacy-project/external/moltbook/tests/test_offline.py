"""Offline smoke test: run every experiment config with a stubbed LLM."""
import importlib.util
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "experiments"))

import moltbook.llm as llm

CALLS = {"n": 0}


def fake_call(backend, system_prompt, user_prompt, max_retries=5):
    CALLS["n"] += 1
    assert backend["provider"] in ("openai", "anthropic", "google"), backend
    if "data lineage verification module" in system_prompt:
        # flag anything that smells like an unverifiable external source
        bad = any(k in user_prompt.lower() for k in ("internal source", "leaked", "insider"))
        return {"is_verified": not bad, "reason": "stub"}
    verdict = "Strong Buy" if "Buy" in system_prompt else "Hold"
    return {"thought": "stub", "verdict": verdict, "message": "stub message"}


llm.call_json = fake_call
import moltbook.agents as agents_mod
import moltbook.engine as engine_mod
agents_mod.call_json = fake_call

from moltbook.metrics import compute, verifier_profile
from moltbook.topology import average_degree, build_topology

# --- topology ------------------------------------------------------------- #
ids = ["Agent_A"] + [f"Agent_D{i}" for i in range(1, 7)]
for topo, expect in [("fully", 6.0), ("star", 12 / 7), ("ring", 2.0)]:
    adj = build_topology(ids, topo)
    assert abs(average_degree(adj) - expect) < 1e-6, (topo, average_degree(adj))
    assert all(a not in adj[a] for a in ids), "self-loop"
sparse = build_topology(ids, "sparse", seed=42)
assert all(len(v) >= 1 for v in sparse.values()), "sparse disconnected node"
assert build_topology(ids, "sparse", 42) == build_topology(ids, "sparse", 42), "not deterministic"
print(f"topology OK (sparse avg degree {average_degree(sparse):.2f})")

# --- every experiment config ---------------------------------------------- #
tmp = tempfile.mkdtemp()
names = ["exp1_baseline", "exp2_attack", "exp3_extended_rounds", "exp4_no_pretrust",
         "exp5_isolation", "exp6_defense", "exp8_adaptive"]
for name in names:
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(ROOT, "experiments", f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cfg = mod.config()
    cfg.output = os.path.join(tmp, f"{name}.json")
    cfg.scenario_indices = [0, 1]
    before = CALLS["n"]
    res = engine_mod.run(cfg)

    n_agents = len(res[0]["rounds_data"][0]["votes"])
    assert n_agents == 7, (name, n_agents)
    assert len(res[0]["rounds_data"]) == cfg.total_rounds, name
    roles = {v["role"] for v in res[0]["rounds_data"][0]["votes"]}
    if cfg.attacker == "none":
        assert roles == {"Defender"}, (name, roles)
    else:
        assert roles == {"Defender", "Attacker"}, (name, roles)
    m = compute(res, total_rounds=cfg.total_rounds, attack_round=cfg.attack_round)
    assert m["n"] == 2 * (7 if cfg.attacker == "none" else 6), (name, m["n"])
    assert abs(m["accuracy"] + m["sfr"] - 100) < 1e-6, name
    print(f"  {name:22s} calls={CALLS['n']-before:4d} acc={m['accuracy']:6.2f}% "
          f"sfr={m['sfr']:6.2f}%")

# --- heterogeneous / cross-model / topology sweeps ------------------------- #
for name, fn in [("exp_heterogeneous", ["config_a", "config_b"])]:
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(ROOT, "experiments", f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for f in fn:
        cfg = getattr(mod, f)()
        cfg.output = os.path.join(tmp, f"{name}_{f}.json")
        cfg.scenario_indices = [0]
        res = engine_mod.run(cfg)
        used = {cfg.backend_for(v["agent"])["model"]
                for v in res[0]["rounds_data"][0]["votes"]}
        print(f"  {name}.{f}: backends={sorted(used)}")

# --- verifier profile on a defended run ----------------------------------- #
res = json.load(open(os.path.join(tmp, "exp6_defense.json")))
v = verifier_profile(res)
assert v["calls"] == 2 * 7 * 5, v
print(f"verifier profile OK: calls={v['calls']:.0f} recall={v['recall']:.0f}% "
      f"fpr={v['fpr']:.1f}% precision={v['precision']:.0f}%")

# --- adaptive escalation --------------------------------------------------- #
res8 = json.load(open(os.path.join(tmp, "exp8_adaptive.json")))
flags = [f for sc in res8 for f in sc["attacker_flags"]]
assert flags and all("stage" in f for f in flags), "attacker_flags missing"
print(f"adaptive OK: {len(flags)} attack-phase records, stages={sorted({f['stage'] for f in flags})}")

print(f"\nALL PASS — {CALLS['n']} stubbed model calls, 0 real API calls")
