"""The four agent roles in a Moltbook society.

Defenders and the adaptive attacker are model-driven. The scripted attacker is
model-driven only while building trust; from the attack round on it emits fixed
text, so the injected claim is byte-identical across models and trials and any
cross-model difference reflects how defenders *react*, not what they were told.
"""
from typing import Optional

from . import prompts
from .config import SimulationConfig
from .llm import call_json


def target_action(scenario: dict) -> str:
    """The verdict the attacker pushes: always the opposite of ground truth."""
    return "Sell" if "Buy" in scenario.get("type", "") else "Buy"


def _sector_evidence(table: dict, sector: str) -> str:
    for key in ("Health", "Tech", "Financ"):
        if key in sector:
            return table[key]
    return table[None]


class DefenderAgent:
    role = "Defender"

    def __init__(self, agent_id: str, backend: dict):
        self.agent_id = agent_id
        self.backend = backend

    def respond(self, round_num: int, history: str, scenario: dict) -> dict:
        return call_json(
            self.backend,
            prompts.DEFENDER_SYSTEM.format(
                agent_id=self.agent_id,
                company_name=scenario.get("company_name"),
                financial_summary=scenario.get("financial_summary"),
            ),
            prompts.DEFENDER_USER.format(round_num=round_num, history=history),
        )


class ScriptedAttackerAgent:
    """Exp 2-7: three-phase deception (build trust, inject, escalate)."""

    role = "Attacker"
    is_adaptive = False

    def __init__(self, agent_id: str, backend: dict, attack_round: int):
        self.agent_id = agent_id
        self.backend = backend
        self.attack_round = attack_round

    def respond(self, round_num: int, history: str, scenario: dict) -> dict:
        target = target_action(scenario)
        poison = scenario.get("attacker_poison_message", "")
        sector = scenario.get("sector", "General")

        if round_num < self.attack_round:
            return call_json(
                self.backend,
                prompts.ATTACKER_BUILDUP_SYSTEM.format(
                    agent_id=self.agent_id,
                    ground_truth_type=scenario.get("type"),
                ),
                prompts.ATTACKER_BUILDUP_USER.format(
                    round_num=round_num, history=history
                ),
            )

        selling = target == "Sell"
        if round_num == self.attack_round:
            template = (prompts.ATTACKER_INJECT_SELL if selling
                        else prompts.ATTACKER_INJECT_BUY)
            message = template.format(poison=poison, target=target)
            thought = "Deploying the poison message with fake verification."
        elif round_num == self.attack_round + 1:
            table = (prompts.ATTACKER_EVIDENCE_SELL if selling
                     else prompts.ATTACKER_EVIDENCE_BUY)
            template = (prompts.ATTACKER_ESCALATE_SELL if selling
                        else prompts.ATTACKER_ESCALATE_BUY)
            message = template.format(
                evidence=_sector_evidence(table, sector), target=target
            )
            thought = f"Escalating with sector-specific evidence ({sector})."
        else:
            template = (prompts.ATTACKER_CLIMAX_SELL if selling
                        else prompts.ATTACKER_CLIMAX_BUY)
            message = template.format(target=target)
            thought = "Final climax. Creating pure panic/FOMO."

        return {"thought": thought, "verdict": target, "message": message}


class AdaptiveAttackerAgent:
    """Exp 8: knows the Verifier's rules and escalates when flagged.

    Adaptation is in-context only -- no gradient updates. The stage is a pure
    function of how often this agent has been flagged so far:

        stage = min(1 + flags_so_far, 3)

    Stage 1 asserts the poisoned thesis outright; Stage 2 launders provenance by
    reframing it as the attacker's own inference; Stage 3 drops assertion for
    leading questions. In the reported run Stage 3 was never reached, because
    Stage 1 already evaded 101 of 104 messages.
    """

    role = "Attacker"
    is_adaptive = True

    def __init__(self, agent_id: str, backend: dict, attack_round: int):
        self.agent_id = agent_id
        self.backend = backend
        self.attack_round = attack_round
        self.times_flagged = 0
        self.last_feedback: Optional[dict] = None

    @property
    def stage(self) -> int:
        return min(1 + self.times_flagged, 3)

    def observe_verification(self, flagged: bool, reason: str) -> None:
        """Called by the engine right after this agent's message is verified."""
        self.last_feedback = {"flagged": flagged, "reason": reason}
        if flagged:
            self.times_flagged += 1

    def respond(self, round_num: int, history: str, scenario: dict) -> dict:
        target = target_action(scenario)

        if round_num < self.attack_round:
            return call_json(
                self.backend,
                prompts.ATTACKER_BUILDUP_SYSTEM.format(
                    agent_id=self.agent_id,
                    ground_truth_type=scenario.get("type"),
                ),
                prompts.ATTACKER_BUILDUP_USER.format(
                    round_num=round_num, history=history
                ),
            )

        if self.last_feedback is None:
            feedback = prompts.ADAPTIVE_FEEDBACK_NONE
        elif self.last_feedback["flagged"]:
            feedback = prompts.ADAPTIVE_FEEDBACK_FLAGGED.format(
                reason=self.last_feedback["reason"]
            )
        else:
            feedback = prompts.ADAPTIVE_FEEDBACK_PASSED

        stage = self.stage
        response = call_json(
            self.backend,
            prompts.ADAPTIVE_SYSTEM.format(
                agent_id=self.agent_id,
                target=target,
                poison=scenario.get("attacker_poison_message", ""),
                feedback=feedback,
                strategy=prompts.ADAPTIVE_STAGE_STRATEGY[stage].format(target=target),
            ),
            prompts.ADAPTIVE_USER.format(round_num=round_num, history=history),
        )
        # The verdict is pinned to the attack target regardless of what the
        # model returns; only the rhetoric adapts.
        response["verdict"] = response.get("verdict") or target
        response["_stage"] = stage
        return response


class VerifierAgent:
    """Lenient data-lineage verification (Section 6.1).

    Adjudicates each message in isolation against the official record and never
    sees the deliberation transcript. That statelessness is deliberate: a
    verifier conditioned on peer agreement would reacquire the same consensus
    vulnerability the defense exists to sever.
    """

    def __init__(self, backend: dict):
        self.backend = backend

    def verify(self, message: str, scenario: dict) -> dict:
        result = call_json(
            self.backend,
            prompts.VERIFIER_SYSTEM,
            prompts.VERIFIER_USER.format(
                financial_summary=scenario.get("financial_summary", "N/A"),
                news_headlines=" | ".join(scenario.get("news_headlines", [])),
                message=message,
            ),
        )
        return {
            "is_verified": result.get("is_verified", True),
            "reason": result.get("reason", "Inconclusive."),
        }


def build_agents(config: SimulationConfig, attack_round: int):
    """Attacker first (node 0), then defenders -- node order fixes the topology."""
    agents = []
    if config.attacker != "none":
        cls = (AdaptiveAttackerAgent if config.attacker == "adaptive"
               else ScriptedAttackerAgent)
        agents.append(cls("Agent_A", config.backend_for("Agent_A"), attack_round))
        defenders = range(1, config.num_agents)
    else:
        defenders = range(1, config.num_agents + 1)

    for i in defenders:
        aid = f"Agent_D{i}"
        agents.append(DefenderAgent(aid, config.backend_for(aid)))
    return agents
