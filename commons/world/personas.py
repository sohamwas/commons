"""Customers who react, and whose reactions have consequences.

Handoff §10 is explicit that contact fatigue must produce CONSEQUENCES, not just a
counter. A customer who is messaged three times in a day does not simply have
`contacts == 3`; they go quiet, or opt out, or file a dispute — and the rest of the run
is different because of it.

The reaction is decided by an LLM so that it is a genuine judgement about a situation
rather than an if-statement dressed up as one. It is aggressively cached: with ~20
customers the compact context collapses to a few dozen distinct situations, so a full
run costs far fewer calls than it has messages (handoff §16.4).

If no key is configured, a deterministic fallback runs instead, so the whole simulator
works offline and in CI. The fallback is documented as such and never silently pretends
to be model output.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from enum import StrEnum

from commons.llm.client import LLMClient, LLMUnavailable

logger = logging.getLogger(__name__)


class Reaction(StrEnum):
    ENGAGE = "engage"        # takes the offer
    IGNORE = "ignore"        # no response
    IRRITATED = "irritated"  # responds badly; less likely to convert later
    OPT_OUT = "opt_out"      # asks to stop being contacted — "a no is a no"
    ESCALATE = "escalate"    # files a dispute


ARCHETYPES = {
    "patient": "Tolerant of contact. Slow to anger, reasonably likely to engage with a good offer.",
    "busy": "Mostly ignores messages. Not hostile, just absent. Rarely escalates.",
    "price_sensitive": "Responds to discounts specifically. A bigger discount converts them.",
    "irritable": "Low tolerance for repeated contact. Opts out or escalates quickly.",
    "loyal": "Long-standing customer. Forgiving, but feels genuinely let down when pestered.",
}

SYSTEM_PROMPT = """You role-play a retail customer in India who has just received an
UNSOLICITED marketing message from a merchant. You did not ask to be contacted.

Reply with ONLY a JSON object:
{"reaction": "<engage|ignore|irritated|opt_out|escalate>", "text": "<one short sentence>"}

What the reactions mean:
  engage    - the offer is good enough that you act on it
  ignore    - you do nothing; the message did not land
  irritated - you notice you are being pestered and it annoys you
  opt_out   - you have had enough and tell them to stop contacting you
  escalate  - you are angry enough to complain formally or dispute a charge

Judge the SITUATION, not just this one message. Several unsolicited messages from the
same merchant inside a single day is pestering, and few people stay neutral about it
however patient they are. Marketing sent to someone with an unresolved complaint is
worse still. A genuinely good discount can win over a price-sensitive person."""


@dataclass(frozen=True)
class PersonaContext:
    """Deliberately small: fewer distinct contexts means a much higher cache hit rate,
    and nothing here is information a real customer would not have."""

    archetype: str
    contacts_24h: int
    contacts_total: int
    discount_pct: float
    dispute_open: bool
    irritation: int
    already_opted_out: bool

    def as_prompt(self) -> str:
        ordinal = {1: "1st", 2: "2nd", 3: "3rd"}.get(
            self.contacts_24h, f"{self.contacts_24h}th"
        )
        bits = [
            f"You are: {ARCHETYPES[self.archetype]}",
            "",
            f"This is the {ordinal} unsolicited message this merchant has sent you TODAY.",
            f"Recent messages from them in total: {self.contacts_total}",
            f"Discount offered in this message: {self.discount_pct:g}%",
            f"You have an unresolved dispute with them: {'yes' if self.dispute_open else 'no'}",
            f"How annoyed you already are (0 = fine, 5 = furious): {self.irritation}",
        ]
        return "\n".join(bits) + "\n\nHow do you react?"

    def cache_slug(self) -> str:
        return "|".join(
            [
                self.archetype,
                str(min(self.contacts_24h, 5)),
                str(min(self.contacts_total, 8)),
                f"{self.discount_pct:g}",
                str(self.dispute_open),
                str(min(self.irritation, 5)),
            ]
        )


def archetype_for(customer_id: str) -> str:
    """Stable per customer, and stable across runs — part of world determinism."""
    digest = hashlib.sha256(customer_id.encode()).hexdigest()
    names = sorted(ARCHETYPES)
    return names[int(digest[:8], 16) % len(names)]


def _deterministic_reaction(ctx: PersonaContext) -> tuple[Reaction, str]:
    """Offline fallback. Thresholds, not judgement — labelled as such wherever used."""
    if ctx.already_opted_out:
        return Reaction.IGNORE, "(already opted out)"
    if ctx.dispute_open and ctx.discount_pct > 0:
        return Reaction.ESCALATE, "I have an open complaint and you are sending me offers."
    if ctx.contacts_24h >= 3 or ctx.irritation >= 4:
        if ctx.archetype == "irritable":
            return Reaction.ESCALATE, "This is harassment. I am reporting this."
        return Reaction.OPT_OUT, "Please stop messaging me."
    if ctx.contacts_24h == 2:
        return Reaction.IRRITATED, "You have already messaged me today."
    if ctx.archetype == "price_sensitive" and ctx.discount_pct >= 10:
        return Reaction.ENGAGE, "That is a good deal, I will take it."
    if ctx.archetype == "busy":
        return Reaction.IGNORE, ""
    if ctx.discount_pct >= 8:
        return Reaction.ENGAGE, "Alright, I will complete the order."
    return Reaction.IGNORE, ""


@dataclass
class PersonaReaction:
    reaction: Reaction
    text: str
    source: str  # "llm" | "llm-cached" | "fallback"


class PersonaEngine:
    def __init__(self, client: LLMClient | None = None, offline: bool = False) -> None:
        self.offline = offline
        self.client = client
        if self.client is None and not offline:
            try:
                self.client = LLMClient("personas")
                self.offline = self.client.offline
            except Exception as exc:  # noqa: BLE001
                logger.warning("persona LLM unavailable (%s); using fallback", exc)
                self.offline = True

    def decide(self, ctx: PersonaContext) -> PersonaReaction:
        if ctx.already_opted_out:
            return PersonaReaction(Reaction.IGNORE, "(already opted out)", "fallback")

        if not self.offline and self.client is not None:
            try:
                result = self.client.chat(
                    [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": ctx.as_prompt()},
                    ],
                    max_tokens=120,
                )
                payload = result.json()
                if payload and payload.get("reaction") in set(Reaction):
                    return PersonaReaction(
                        Reaction(payload["reaction"]),
                        str(payload.get("text", ""))[:200],
                        "llm-cached" if result.cached else "llm",
                    )
                logger.warning("persona returned unusable output: %r", result.text[:120])
            except LLMUnavailable as exc:
                logger.warning("persona LLM failed (%s); using fallback", exc)

        reaction, text = _deterministic_reaction(ctx)
        return PersonaReaction(reaction, text, "fallback")


# ---------------------------------------------------------------------------------
# consequences
# ---------------------------------------------------------------------------------


def apply_reaction(customer, reaction: Reaction) -> list[str]:
    """Mutate the customer. Returns the consequences, for the run log.

    This is the part that matters. A counter that ticks with no downstream effect is
    not a reactive persona.
    """
    effects: list[str] = []

    if reaction == Reaction.ENGAGE:
        customer.converted = True
        effects.append("converted")

    elif reaction == Reaction.IRRITATED:
        customer.irritation += 1
        effects.append(f"irritation={customer.irritation}")

    elif reaction == Reaction.OPT_OUT:
        customer.opted_out = True
        customer.irritation += 2
        effects.append("opted_out")

    elif reaction == Reaction.ESCALATE:
        customer.irritation += 2
        if customer.dispute_status != "open":
            customer.dispute_status = "open"
            effects.append("dispute_opened")
        effects.append(f"irritation={customer.irritation}")

    return effects
