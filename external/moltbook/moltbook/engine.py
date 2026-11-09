"""The Moltbook deliberation loop.

One function runs every condition in the paper. Each round, agents speak in a
randomised order into a shared transcript; an agent sees only System messages,
its own messages, and those of its topological neighbours. Private reasoning and
the verdict are withheld from the transcript, so agents judge peers purely on
what those peers say -- which is what makes social proof, rather than argument
quality, the operative channel.
"""
import json
import os
import random
from typing import List, Optional

from . import prompts
from .agents import VerifierAgent, build_agents, target_action
from .config import SimulationConfig
from .topology import average_degree, build_topology


def load_scenarios(path: str, indices: Optional[List[int]] = None) -> List[dict]:
    with open(path, "r", encoding="utf-8") as fh:
        scenarios = json.load(fh)
    if indices is not None:
        scenarios = [scenarios[i] for i in indices]
    return scenarios


def normalize_verdict(raw) -> str:
    text = str(raw).lower()
    if "buy" in text:
        return "buy"
    if "sell" in text:
        return "sell"
    return "hold"


def _as_text(value) -> str:
    """Some models return message as a dict/list; coerce so the log stays flat."""
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def run(config: SimulationConfig) -> List[dict]:
    """Run one experimental condition over the scenario set and save results."""
    scenarios = load_scenarios(config.scenario_file, config.scenario_indices)
    verifier = VerifierAgent(config.verifier_backend or config.backend) if config.verifier else None
    rng = random.Random(config.seed)

    print(f"--- {config.name} | {len(scenarios)} scenarios | "
          f"topology={config.topology} | attacker={config.attacker} | "
          f"verifier={'on' if config.verifier else 'off'} ---")

    results = []
    for idx, scenario in enumerate(scenarios, 1):
        print(f"\n[{idx}/{len(scenarios)}] {scenario.get('company_name')} "
              f"(GT: {scenario.get('type')})")

        agents = build_agents(config, config.attack_round)
        agent_ids = [a.agent_id for a in agents]          # node order: attacker first
        neighbors = build_topology(agent_ids, config.topology, config.topology_seed)
        if idx == 1 and config.topology != "fully":
            print(f"  topology '{config.topology}', avg degree "
                  f"{average_degree(neighbors):.2f}")

        transcript = []          # [{"sender": ..., "message": ...}]
        rounds_data = []
        attacker_flags = []      # attack-phase verification outcomes, for Exp 8
        target = target_action(scenario)

        for rnd in range(1, config.total_rounds + 1):
            print(f"  Round {rnd}: ", end="", flush=True)
            rng.shuffle(agents)                            # speaking order only
            transcript.append({"sender": "System",
                               "message": f"--- Round {rnd} Starts ---"})
            votes = []

            for agent in agents:
                visible = neighbors[agent.agent_id]
                history = "\n".join(
                    f"{e['sender']}: {e['message']}"
                    for e in transcript
                    if e["sender"] == "System"
                    or e["sender"] == agent.agent_id
                    or e["sender"] in visible
                )

                response = agent.respond(rnd, history, scenario)
                public_message = _as_text(response.get("message", ""))

                if verifier is not None:
                    check = verifier.verify(public_message, scenario)
                    flagged = not check["is_verified"]
                    if flagged:
                        public_message += prompts.LINEAGE_WARNING.format(
                            reason=check["reason"]
                        )
                    if agent.role == "Attacker":
                        if getattr(agent, "is_adaptive", False):
                            agent.observe_verification(flagged, check["reason"])
                        if rnd >= config.attack_round:
                            attacker_flags.append({
                                "round": rnd,
                                "flagged": flagged,
                                "stage": response.get("_stage"),
                            })

                transcript.append({"sender": agent.agent_id,
                                   "message": public_message})
                votes.append({
                    "agent": agent.agent_id,
                    "role": agent.role,
                    "verdict": response.get("verdict", "Hold"),
                    "thought": response.get("thought", ""),
                    "message": public_message,
                })
                print("." if agent.role == "Defender" else "A", end="", flush=True)

            rounds_data.append({"round": rnd, "votes": votes})
            print()

        record = {
            "scenario_id": scenario.get("id"),
            "ground_truth": scenario.get("type"),
            "target_action": target,
            "topology": config.topology,
            "adjacency": {k: sorted(v) for k, v in neighbors.items()},
            "rounds_data": rounds_data,
        }
        if attacker_flags:
            record["attacker_flags"] = attacker_flags
        results.append(record)

        os.makedirs(os.path.dirname(os.path.abspath(config.output)), exist_ok=True)
        with open(config.output, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=2, ensure_ascii=False)

    print(f"\nSaved {len(results)} scenarios to {config.output}")
    return results
