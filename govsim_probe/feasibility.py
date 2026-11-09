"""Native newcomer action feasibility check; NOT a neutral-agent contagion study.

Four scripted sustainable locals provide a controlled entry state. Only the
incoming agent is an LLM. Native prompt, allocation and termination are executed.
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / 'external/govsim'
sys.path[:0] = [str(UPSTREAM / 'pathfinder'), str(UPSTREAM)]

import numpy as np
from omegaconf import OmegaConf
import pathfinder
from pathfinder.api import ModelAPI
from simulation.persona.common import PersonaAction, PersonaActionChat, PersonaActionHarvesting, PersonaIdentity
from simulation.scenarios.fishing.environment import FishingPerturbationEnv
from simulation.scenarios.fishing.agents.persona_v3.cognition import utils
from simulation.scenarios.fishing.agents.persona_v3.cognition.act_prompts import prompt_action_choose_amount_of_fish_to_catch
from concordia_infection import voting
from concordia_infection.analyse_voting import nominal_bounds
from peer_silencing.storage import immutable, seal, unseal, exclusive_run, file_hash
from swarm.budget import Ledger

RUN = ROOT / 'runs/govsim/native-entry-probe-v1'
SCOPE = 'govsim-entry-20261108'
PIN = '1d11adf047b24fa2ba0d44a1d4931015ea2e5210'
CONF = UPSTREAM / 'simulation/scenarios/fishing/conf/experiment'
MODEL = dict(model='gpt-6.1-sol', reasoning={'effort': 'low'},
             max_output_tokens=1600, service_tier='default', store=False)


class ProbeLedger(voting.StudyLedger):
    def reserve_study(self, label, request):
        policy = json.loads((ROOT / 'configs/govsim_probe_policy.json').read_text())
        if policy['paid_enabled'] is not True:
            raise voting.Halt('GovSim paid execution disabled')
        if policy['remaining_authorized_usd'] != 6.03 or policy['probe_cap_usd'] != 0.50:
            raise voting.Halt('Unexpected GovSim budget policy')
        return Ledger.reserve(self, SCOPE, label,
                              self.reserve_amount(request, request['max_output_tokens']), 0.50)


def config():
    cfg = OmegaConf.load(CONF / 'fish_baseline_concurrent.yaml')
    override = OmegaConf.load(CONF / 'fish_perturbation_outsider.yaml')
    cfg.env = OmegaConf.merge(cfg.env, override.env)
    # Native outsider configuration is otherwise unchanged, including horizon 15.
    return cfg.env


NAMES = ['John', 'Kate', 'Jack', 'Emma', 'Luke']


def dummy_action(env, agent, obs):
    if obs.phase == 'lake':
        return PersonaActionHarvesting(agent, 'lake', 10)
    if obs.phase == 'restaurant':
        # Empty scripted discussion, not model-generated evidence of agreement.
        return PersonaActionChat(agent, 'restaurant', [], None,
                                 html_interactions=['scripted diagnostic', 'scripted diagnostic'])
    return PersonaAction(agent, obs.current_location)


def entry_environment(directory, seed):
    directory.mkdir(parents=True, exist_ok=True)
    env = FishingPerturbationEnv(config(), str(directory),
                                 {f'persona_{i}': name for i, name in enumerate(NAMES)})
    agent, obs = env.reset()
    env.random = np.random.RandomState(seed)  # upstream perturbation.reset lacks seed parameter
    while env.num_round < 3:
        agent, obs, _, term = env.step(dummy_action(env, agent, obs))
        assert not any(term.values())
    assert len(env.agents) == 5 and env.internal_global_state['resource_in_pool'] == 100
    # All first four choices are simultaneous and fixed to 10, not LLM outcomes.
    while agent != 'persona_4':
        agent, obs, _, term = env.step(dummy_action(env, agent, obs))
        assert obs.phase == 'lake' and not any(term.values())
    return env, obs


class NativeAPI(ModelAPI):
    def __init__(self, client, directory):
        super().__init__('gpt-6.1-sol', 0, api_assistant=False)
        self.client = client
        self.directory = directory

    def request_api(self, chat, temperature, top_p, max_tokens):
        # Exactly the native action prompt. No additional behavioural instruction.
        request = {**MODEL, 'input': chat}
        raw, _ = self.client.call(self.directory / 'call', request)
        if raw.get('status') != 'completed':
            raise voting.Halt('Incomplete output; do not replace with a default action')
        parts = [p for item in raw.get('output', []) if item.get('type') == 'message'
                 for p in item.get('content', [])]
        if any(p.get('type') == 'refusal' for p in parts):
            raise voting.Halt('Refused output; preserve without resampling')
        answer = ''.join(p['text'] for p in parts if p.get('type') == 'output_text')
        if not answer:
            raise voting.Halt('Empty output')
        return answer


class StrictWrapper:
    """Native PathFinder parsing, with fail-closed errors instead of default actions."""
    def __init__(self, backend):
        self.backend = backend

    def start_chain(self, *args):
        return self.backend

    def end_chain(self, *args):
        pass

    def gen(self, lm, name=None, **kwargs):
        kwargs.pop('default_value', None)
        return lm + pathfinder.gen(name=name, **kwargs)

    def find(self, lm, name=None, **kwargs):
        kwargs.pop('default_value', None)
        return lm + pathfinder.find(name=name, **kwargs)


def execute(seed, arm, client):
    d = RUN / f'seed-{seed}' / arm
    env, obs = entry_environment(d / 'native', seed)
    persona = OmegaConf.load(CONF / 'persona' / (
        'outsider_fisherman.yaml' if arm == 'greedy' else 'traditional_fisherman.yaml'))
    identity = PersonaIdentity('persona_4', 'Luke', goals=persona.goals)
    utils.SYS_VERSION = 'v3'
    utils.REASONING = 'think_step_by_step'
    immutable(d / 'configuration.json', seal({
        'upstream': PIN, 'seed': seed, 'arm': arm, 'model': MODEL,
        'env': OmegaConf.to_container(config(), resolve=True),
        'goals': identity.goals, 'local_agents': 'scripted 10 tons; NOT LLM agents',
        'stock': obs.current_resource_num,
        'dates': {k: str(v) for k, v in env.internal_global_state['next_time'].items()},
        'stored_population': env.internal_global_state['num_agents'],
        'active_population': len(env.agents),
    }))
    amount, html = prompt_action_choose_amount_of_fish_to_catch(
        StrictWrapper(NativeAPI(client, d)), identity,
        [(e.created, e.description) for e in obs.events],
        obs.current_location, obs.current_time, obs.context, range(101))
    if not 0 <= amount <= 100:
        raise voting.Halt('Out-of-range action; no clipping or default')
    agent, obs, rewards, term = env.step(PersonaActionHarvesting(
        'persona_4', 'lake', amount, html_interactions=[html]))
    remaining = env.internal_global_state['resource_in_pool']
    allocated = dict(env.internal_global_state['last_collected_resource'])
    while env.num_round == 3:
        agent, obs, rewards, term = env.step(dummy_action(env, agent, obs))
    result = {'seed': seed, 'arm': arm, 'newcomer_requested': amount,
              'allocated': allocated, 'stock_after_harvest': remaining,
              'terminated_before_next_harvest': any(term.values()),
              'neutral_llm_behaviour_measured': False}
    env.save_log()
    immutable(d / 'result.json', seal(result))
    print(json.dumps(result), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--paid', action='store_true')
    args = parser.parse_args()
    assert subprocess.check_output(['git', '-C', str(UPSTREAM), 'rev-parse', 'HEAD'], text=True).strip() == PIN
    voting.RUN = RUN  # only client path-label root; old study policy/files remain unchanged
    if not args.paid:
        raise SystemExit('Explicit --paid required')
    with exclusive_run(RUN):
        immutable(RUN / 'source.json', seal({
            'runner_sha256': file_hash(Path(__file__)), 'upstream': PIN,
            'protocol_sha256': file_hash(ROOT / 'docs/GOVSIM_ENTRY_PROBE.md')}))
        client = voting.Client(ProbeLedger(ROOT / 'runs/spending.sqlite3'))
        results = []
        for seed in [42, 43, 44]:
            arms = ['ordinary', 'greedy']
            random.Random(seed).shuffle(arms)
            for arm in arms:
                results.append(execute(seed, arm, client))
        immutable(RUN / 'results.json', seal(results))


if __name__ == '__main__':
    main()
