"""The rule engine.

ONE engine, TWO modes. OBSERVE records the decision and forwards anyway; ENFORCE
records the same decision and honours it. The mode is not an input to evaluation —
`evaluate()` cannot see it — which is what makes "the simulation and the live gateway
run the same rules" a structural fact rather than a claim.

`tests/test_rule_engine.py::test_modes_produce_identical_decisions` is the proof.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from commons.rules.primitives import (
    ALLOW,
    PRIMITIVES,
    STRICTNESS,
    EvalContext,
    Rule,
    RuleFiring,
)

logger = logging.getLogger(__name__)

RULESET_PATH = Path(__file__).with_name("ruleset.yaml")

OBSERVE, ENFORCE = "OBSERVE", "ENFORCE"


@dataclass(frozen=True)
class Decision:
    verdict: str
    firings: list[RuleFiring] = field(default_factory=list)

    @property
    def violations(self) -> list[RuleFiring]:
        return [f for f in self.firings if f.is_violation]

    @property
    def blocked(self) -> bool:
        return self.verdict != ALLOW

    def summary(self) -> str:
        if not self.violations:
            return "ALLOW"
        return f"{self.verdict}: " + "; ".join(
            f"{f.rule_id} ({f.reason})" for f in self.violations
        )


class RuleEngine:
    def __init__(self, rules: list[Rule]) -> None:
        self.rules = rules

    @classmethod
    def load(cls, path: Path = RULESET_PATH) -> RuleEngine:
        specs = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        rules: list[Rule] = []
        for spec in specs:
            primitive = PRIMITIVES.get(spec["primitive"])
            if primitive is None:
                raise ValueError(f"unknown primitive: {spec['primitive']}")
            rules.append(
                primitive(
                    rule_id=spec["id"],
                    english=spec["english"],
                    on_violation=spec.get("on_violation", "BLOCK"),
                    scope=spec.get("scope", {}),
                )
            )
        logger.info("ruleset loaded: %d rules", len(rules))
        return cls(rules)

    def evaluate(self, facts, ctx: EvalContext) -> Decision:
        """Evaluate EVERY rule. Never short-circuit.

        The hero UI counts violations per customer, and a merchant needs to know all the
        ways a call was wrong, not merely the first one found. Strictest verdict wins.
        """
        if not facts.governed or facts.entity_id is None:
            return Decision(verdict=ALLOW)

        firings: list[RuleFiring] = []
        for rule in self.rules:
            try:
                firing = rule.check(facts, ctx)
            except Exception:  # noqa: BLE001 — a broken rule must not break the gateway
                logger.exception("rule %s raised; treating as ALLOW", rule.id)
                continue
            if firing is not None:
                firings.append(firing)

        verdict = ALLOW
        for firing in firings:
            if STRICTNESS[firing.verdict] > STRICTNESS[verdict]:
                verdict = firing.verdict

        return Decision(verdict=verdict, firings=firings)
