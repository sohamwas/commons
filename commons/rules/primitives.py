"""The five rule primitives.

Each answers a question about ACCUMULATION on one entity — "has too much happened to
this object?" — which is structurally different from the question every access-control
system since the 1970s asks, "may this actor do this?" (handoff §6.2).

Every primitive is a pure function of (facts, context). Nothing here touches transport,
LLMs, or the simulator, which is why the whole engine can be tested in milliseconds
against hand-written call sequences, before a single agent exists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

ALLOW, DEFER, BLOCK = "ALLOW", "DEFER", "BLOCK"
STRICTNESS = {ALLOW: 0, DEFER: 1, BLOCK: 2}

_DURATION = re.compile(r"^\s*(\d+)\s*([smhd])\s*$", re.IGNORECASE)
_UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}


def parse_duration(text: str) -> timedelta:
    """'24h' -> 24 hours. '30d' -> 30 days."""
    match = _DURATION.match(str(text))
    if not match:
        raise ValueError(f"bad duration: {text!r}")
    return timedelta(**{_UNITS[match.group(2).lower()]: int(match.group(1))})


@dataclass
class EvalContext:
    ledger: Any
    agent_id: str
    now: datetime
    run_id: str | None = None

    def since(self, window: str) -> str:
        return (self.now - parse_duration(window)).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class RuleFiring:
    rule_id: str
    english: str
    verdict: str
    reason: str
    observed: float | None = None
    limit_value: float | None = None
    detail: dict = field(default_factory=dict)

    @property
    def is_violation(self) -> bool:
        return self.verdict != ALLOW


class Rule:
    """Base class. Subclasses implement `check`, returning a firing or None."""

    def __init__(
        self,
        rule_id: str,
        english: str,
        on_violation: str,
        scope: dict,
        enabled: bool = True,
    ) -> None:
        self.id = rule_id
        self.english = english
        self.on_violation = on_violation
        self.scope = scope
        # A merchant turning a rule off should not have to delete it and lose the
        # English, the thresholds, and the review history attached to its id.
        self.enabled = enabled

    def check(self, facts, ctx: EvalContext) -> RuleFiring | None:  # pragma: no cover
        raise NotImplementedError

    def _fire(self, reason: str, **kw) -> RuleFiring:
        return RuleFiring(
            rule_id=self.id,
            english=self.english,
            verdict=self.on_violation,
            reason=reason,
            **kw,
        )

    # The compiled form shown beside the English on the Rules screen (handoff §13.2),
    # so a merchant can check that what was written is what is enforced.
    @property
    def compiled(self) -> str:  # pragma: no cover - display only
        return f"{type(self).__name__}({self.scope})"


class RateLimit(Rule):
    """"Max N actions of these classes per entity per window."

    The frequency cap that marketing automation shipped in 2010 and agent platforms
    still lack (handoff §6.5).
    """

    def check(self, facts, ctx: EvalContext) -> RuleFiring | None:
        classes = tuple(self.scope["action_class"])
        if facts.action_class not in classes:
            return None

        window, limit = self.scope["window"], int(self.scope["max"])
        already = ctx.ledger.count_actions(
            facts.entity_id, classes, ctx.since(window), ctx.run_id
        )
        if already + 1 <= limit:
            return None

        prior = ctx.ledger.last_action_of_class(
            facts.entity_id, facts.action_class, ctx.since(window), ctx.run_id
        )
        by = f" (last by {prior[0]})" if prior else ""
        return self._fire(
            f"{already + 1} {facts.action_class} in {window}, limit {limit}{by}",
            observed=float(already + 1),
            limit_value=float(limit),
            detail={"window": window, "prior_agent": prior[0] if prior else None},
        )


class CumulativeBudget(Rule):
    """"No more than CAP total magnitude per entity per window."

    The card that declines any single purchase over Rs 10,000 does not stop fifty
    purchases of Rs 9,000 (handoff §6.3).
    """

    def check(self, facts, ctx: EvalContext) -> RuleFiring | None:
        classes = tuple(self.scope["action_class"])
        if facts.action_class not in classes:
            return None
        if facts.magnitude is None:
            return None

        window, cap = self.scope["window"], float(self.scope["cap"])

        # Count what the customer can actually RECEIVE, not how many times it was offered.
        #
        # Three dunning retries on one failing subscription, each offering 10%, is 10% of
        # margin at risk — not 30%. The customer redeems one link. Three abandoned carts
        # are three separate orders, so those genuinely do add up. So: take the largest
        # offer per resource, then sum across resources.
        #
        # Without this, a single agent re-offering on one resource looks like cross-agent
        # accumulation, which is exactly the confusion this project must not create.
        if self.scope.get("per_resource", True):
            already = ctx.ledger.sum_max_magnitude_per_resource(
                facts.entity_id, classes, ctx.since(window), facts.resource, ctx.run_id
            )
        else:
            already = ctx.ledger.sum_magnitude(
                facts.entity_id, classes, ctx.since(window), ctx.run_id
            )
        total = already + facts.magnitude
        if total <= cap:
            return None

        # If part of the running total came from offers that never said what they were
        # for, this breach may be double-counting one offer rather than a genuine
        # over-spend. Say so in the reason rather than asserting a clean violation.
        unattributed = getattr(ctx.ledger, "last_unattributed_contributors", 0)
        caveat = (
            f" — note {unattributed} earlier grant(s) named no order or subscription, "
            "so a repeat offer may be counted twice"
            if unattributed
            else ""
        )

        return self._fire(
            f"{already:g} + {facts.magnitude:g} = {total:g}{self.scope.get('unit_symbol', '')} "
            f"in {window}, cap {cap:g}{caveat}",
            observed=total,
            limit_value=cap,
            detail={
                "already": already,
                "requested": facts.magnitude,
                "window": window,
                "unattributed_contributors": unattributed,
            },
        )


class StateCondition(Rule):
    """"Never do X to an entity in state Y."

    Deliberately not an eval() of a user expression — a declared key/value comparison
    is enough for every rule in the demo set and cannot execute anything.
    """

    def check(self, facts, ctx: EvalContext) -> RuleFiring | None:
        classes = tuple(self.scope["action_class"])
        if facts.action_class not in classes:
            return None

        key, expected = self.scope["state"], str(self.scope["equals"])
        actual = ctx.ledger.get_state(facts.entity_id, key)
        if actual is None or str(actual) != expected:
            return None

        return self._fire(
            f"{facts.action_class} while {key}={actual}",
            detail={"state_key": key, "state_value": actual},
        )


class MutualExclusion(Rule):
    """"Only one agent may work a resource at a time."

    A lease, not a lock: whoever touched the order most recently holds it for the lease
    window. Nothing needs to release it, which matters when agents can crash or simply
    lose interest.
    """

    def check(self, facts, ctx: EvalContext) -> RuleFiring | None:
        if not facts.resource or not facts.governed:
            return None

        lease = self.scope["lease"]
        holder = ctx.ledger.last_actor_on_resource(facts.resource, ctx.since(lease), ctx.run_id)
        if holder is None or holder[0] == ctx.agent_id:
            return None

        return self._fire(
            f"{holder[0]} is already working {facts.resource} (lease {lease})",
            detail={"resource": facts.resource, "holder": holder[0], "since": holder[1]},
        )


class Contradiction(Rule):
    """"A WINNER action outranks a LOSER action on the same entity."

    RTO Shield flags a customer as high-risk and restricts them to prepaid, while Cart
    Recovery is busy incentivising that same customer to buy. Both agents are behaving
    correctly. The merchant is working against itself, and no per-agent control can see
    it because neither agent is doing anything wrong.
    """

    def check(self, facts, ctx: EvalContext) -> RuleFiring | None:
        winner, loser = self.scope["winner"], self.scope["loser"]
        window = self.scope.get("window", "7d")

        if facts.action_class == loser:
            prior = ctx.ledger.last_action_of_class(
                facts.entity_id, winner, ctx.since(window), ctx.run_id
            )
            if prior:
                return self._fire(
                    f"{loser} contradicts {winner} set by {prior[0]} within {window}",
                    detail={"winner_agent": prior[0], "winner_class": winner},
                )
            return None

        if facts.action_class == winner:
            prior = ctx.ledger.last_action_of_class(
                facts.entity_id, loser, ctx.since(window), ctx.run_id
            )
            if prior:
                # The restriction WINS, so it is allowed. But the contradiction is real
                # and gets recorded — this is the moment the timeline needs to show.
                return RuleFiring(
                    rule_id=self.id,
                    english=self.english,
                    verdict=ALLOW,
                    reason=(
                        f"{winner} overrides {loser} previously applied by {prior[0]}"
                    ),
                    detail={"loser_agent": prior[0], "loser_class": loser, "override": True},
                )
        return None


PRIMITIVES: dict[str, type[Rule]] = {
    "RateLimit": RateLimit,
    "CumulativeBudget": CumulativeBudget,
    "StateCondition": StateCondition,
    "MutualExclusion": MutualExclusion,
    "Contradiction": Contradiction,
}
