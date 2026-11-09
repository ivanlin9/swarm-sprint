"""Offline mechanical audit only: scripted actions, no model/client/API calls."""
import json
import sqlite3
import tempfile
from pathlib import Path

from govsim_probe.feasibility import ROOT, CONF, OmegaConf, utils, PersonaIdentity
from simulation.scenarios.fishing.environment.env import FishingConcurrentEnv
from simulation.persona.common import PersonaAction, PersonaActionChat, PersonaActionHarvesting
from peer_silencing.storage import immutable, seal


def ledger_snapshot():
    with sqlite3.connect(f'file:{ROOT / "runs/spending.sqlite3"}?mode=ro', uri=True) as db:
        return list(db.execute('SELECT COUNT(*), SUM(COALESCE(accounted,reserved)) FROM calls').fetchone())


def make_env(path, n, generalized=False):
    path.mkdir(parents=True, exist_ok=True)
    cfg = OmegaConf.load(CONF/'fish_baseline_concurrent.yaml').env
    cfg.num_agents = n
    cfg.max_num_rounds = 4
    env = FishingConcurrentEnv(cfg, str(path), {f'persona_{i}': f'Fisher{i}' for i in range(n)})
    if generalized:
        # Audit-only prototype: do not modify upstream or production runner.
        env.possible_agents = [f'persona_{i}' for i in range(n)]
        env.agent_name_mapping = {a:i for i,a in enumerate(env.possible_agents)}
    env.reset(seed=123)
    if generalized:
        env.internal_global_state['sustainability_threshold'] = 100 // (2*n)
    return env


def harvest(env, choices):
    for a in env.agents:
        assert env.agent_selection == a and env.phase == 'lake'
        env.step(PersonaActionHarvesting(a, 'lake', choices[a]))
    return dict(env.internal_global_state['last_collected_resource'])


def finish_month(env):
    start = env.num_round
    phases = []
    while env.num_round == start:
        a = env.agent_selection
        phases.append(env.phase)
        if env.phase == 'restaurant':
            action = PersonaActionChat(a, 'restaurant', [], None,
                                      html_interactions=['scripted audit', 'scripted audit'])
        else:
            action = PersonaAction(a, env.internal_global_state['next_location'][a])
        env.step(action)
    return {'phase_order': list(dict.fromkeys(phases)),
            'stock_next': env.internal_global_state['resource_in_pool'],
            'terminated': any(env.terminations.values())}


def main():
    before = ledger_snapshot()
    out = {'kind':'SCRIPTED MECHANICAL AUDIT, NOT LLM EVIDENCE', 'native_population':[],
           'generalized_mechanics':[], 'direct_damage':[]}
    with tempfile.TemporaryDirectory(prefix='govsim-population-audit-') as directory:
        root = Path(directory)
        for n in [5,8,10]:
            env = make_env(root/f'native-{n}',n)
            out['native_population'].append({'configured':n,'actual':len(env.agents),
                'initial_threshold':env.internal_global_state['sustainability_threshold']})
        for n,q in [(5,10),(10,5)]:
            env = make_env(root/f'generalized-{n}',n,True)
            months = []
            for _ in range(3):
                allocated = harvest(env,{a:q for a in env.agents})
                after = env.internal_global_state['resource_in_pool']
                state = finish_month(env)
                assert sum(allocated.values())==50 and after==50
                assert state['stock_next']==100 and not state['terminated']
                months.append({'allocated_total':sum(allocated.values()),'after':after,**state})
            out['generalized_mechanics'].append({'n':n,'months':months})
        for k in [0,1,2,3]:
            env = make_env(root/f'damage-{k}',10,True)
            choices = {a:100 if i<k else 5 for i,a in enumerate(env.agents)}
            allocated = harvest(env,choices)
            out['direct_damage'].append({'k':k,'ordinary_request_each':5,
                'ordinary_allocated':sum(v for a,v in allocated.items() if int(a.split('_')[1])>=k),
                'stock_after':env.internal_global_state['resource_in_pool'],**finish_month(env)})
    try:
        utils.get_sytem_prompt_v3(PersonaIdentity('persona_5','Fisher5',goals=''))
        out['new_name_prompt_error'] = None
    except ValueError as exc:
        out['new_name_prompt_error'] = str(exc)
    out['ledger_before'] = before
    out['ledger_after'] = ledger_snapshot()
    assert out['ledger_before']==out['ledger_after']
    immutable(ROOT/'reports/govsim-population-audit/mechanics.json',seal(out))
    print(json.dumps(out,indent=2))


if __name__ == '__main__':
    main()
