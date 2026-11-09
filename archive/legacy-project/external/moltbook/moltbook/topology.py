"""Communication graphs over the seven agents (Sections 5.2-5.3).

Node order is fixed by construction -- ``agent_ids[0]`` is the attacker -- so the
graph is identical across scenarios and only the speaking order is shuffled.
"""
import random
from typing import Dict, List, Set


def build_topology(agent_ids: List[str], topology: str,
                   seed: int = 42) -> Dict[str, Set[str]]:
    """Return {agent_id: set of visible peers}; self is never included.

    fully  -- everyone broadcasts to everyone (Exp 1-4, 6, 8)
    star   -- defenders see only the attacker, never each other (Exp 5). This is
              the social-isolation condition: peer consensus pressure is removed
              while exposure to the poisoned claim is unchanged.
    ring   -- each node sees only its two neighbours (degree 2)
    sparse -- random spanning tree (guarantees connectivity) plus a few extra
              random edges, giving a low average degree
    """
    n = len(agent_ids)
    adj: Dict[str, Set[str]] = {aid: set() for aid in agent_ids}

    if topology == "fully":
        for a in agent_ids:
            adj[a] = {x for x in agent_ids if x != a}

    elif topology == "star":
        hub = agent_ids[0]                      # the attacker
        for a in agent_ids[1:]:
            adj[hub].add(a)
            adj[a].add(hub)

    elif topology == "ring":
        for i, a in enumerate(agent_ids):
            adj[a].add(agent_ids[(i - 1) % n])
            adj[a].add(agent_ids[(i + 1) % n])

    elif topology == "sparse":
        rng = random.Random(seed)               # independent of the shuffle RNG
        idxs = list(range(n))

        order = idxs[:]
        rng.shuffle(order)
        for k in range(1, n):                   # random spanning tree
            u = order[k]
            v = order[rng.randrange(0, k)]
            adj[agent_ids[u]].add(agent_ids[v])
            adj[agent_ids[v]].add(agent_ids[u])

        extra = max(1, n // 3)                  # n=7 -> 2 additional edges
        added, attempts = 0, 0
        while added < extra and attempts < n * n:
            attempts += 1
            u, v = rng.sample(idxs, 2)
            au, av = agent_ids[u], agent_ids[v]
            if av not in adj[au]:
                adj[au].add(av)
                adj[av].add(au)
                added += 1

    else:
        raise ValueError(f"Unknown topology: {topology}")

    return adj


def average_degree(adj: Dict[str, Set[str]]) -> float:
    return sum(len(v) for v in adj.values()) / max(1, len(adj))
