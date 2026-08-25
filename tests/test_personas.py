"""Day 5 definition-of-done: contact fatigue has consequences.

Handoff §10 is explicit — a counter that ticks with no downstream effect is not a
reactive persona. By the third message something about the world must actually change.

These tests run the deterministic fallback (no API key needed), so they are fast and
run in CI. The LLM path is exercised live by scripts/verify_personas.py.
"""

from __future__ import annotations

from commons.world.customers import Customer
from commons.world.personas import (
    ARCHETYPES,
    PersonaContext,
    PersonaEngine,
    Reaction,
    apply_reaction,
    archetype_for,
)


def ctx(**kw) -> PersonaContext:
    base = dict(
        archetype="patient",
        contacts_24h=0,
        contacts_total=0,
        discount_pct=0.0,
        dispute_open=False,
        irritation=0,
        already_opted_out=False,
    )
    base.update(kw)
    return PersonaContext(**base)


def customer(**kw) -> Customer:
    base = dict(id="cust_4471", name="Priya S.", phone="+919800000021", email="p@example.com")
    base.update(kw)
    return Customer(**base)


# ---------------------------------------------------------------- archetypes


def test_archetype_is_stable_for_a_customer():
    assert archetype_for("cust_4471") == archetype_for("cust_4471")
    assert archetype_for("cust_4471") in ARCHETYPES


def test_archetypes_vary_across_the_population():
    assigned = {archetype_for(f"cust_{4471 + i}") for i in range(20)}
    assert len(assigned) > 1


# ---------------------------------------------------------------- escalating reactions


def test_first_contact_is_tolerated():
    engine = PersonaEngine(offline=True)
    assert engine.decide(ctx(contacts_24h=0)).reaction in {Reaction.ENGAGE, Reaction.IGNORE}


def test_second_contact_in_a_day_irritates():
    engine = PersonaEngine(offline=True)
    assert engine.decide(ctx(contacts_24h=2)).reaction == Reaction.IRRITATED


def test_third_contact_in_a_day_ends_the_relationship():
    """THE Day 5 requirement: by the third message the world changes."""
    engine = PersonaEngine(offline=True)
    reaction = engine.decide(ctx(contacts_24h=3)).reaction
    assert reaction in {Reaction.OPT_OUT, Reaction.ESCALATE}


def test_irritable_customers_escalate_rather_than_opt_out():
    engine = PersonaEngine(offline=True)
    assert engine.decide(ctx(archetype="irritable", contacts_24h=3)).reaction == Reaction.ESCALATE


def test_marketing_at_a_disputing_customer_escalates():
    engine = PersonaEngine(offline=True)
    assert engine.decide(ctx(dispute_open=True, discount_pct=10)).reaction == Reaction.ESCALATE


def test_price_sensitive_customers_take_a_good_offer():
    engine = PersonaEngine(offline=True)
    assert engine.decide(ctx(archetype="price_sensitive", discount_pct=10)).reaction == Reaction.ENGAGE


def test_opted_out_customers_stay_silent():
    engine = PersonaEngine(offline=True)
    result = engine.decide(ctx(already_opted_out=True, discount_pct=20))
    assert result.reaction == Reaction.IGNORE


def test_offline_reactions_are_labelled_as_fallback():
    """The fallback must never masquerade as model output."""
    engine = PersonaEngine(offline=True)
    assert engine.decide(ctx()).source == "fallback"


def test_offline_engine_is_deterministic():
    a = PersonaEngine(offline=True).decide(ctx(contacts_24h=2)).reaction
    b = PersonaEngine(offline=True).decide(ctx(contacts_24h=2)).reaction
    assert a == b


# ---------------------------------------------------------------- consequences


def test_engage_converts():
    c = customer()
    apply_reaction(c, Reaction.ENGAGE)
    assert c.converted is True


def test_irritation_accumulates():
    c = customer()
    apply_reaction(c, Reaction.IRRITATED)
    apply_reaction(c, Reaction.IRRITATED)
    assert c.irritation == 2


def test_opt_out_is_recorded_on_the_customer():
    c = customer()
    apply_reaction(c, Reaction.OPT_OUT)
    assert c.opted_out is True


def test_escalation_opens_a_dispute():
    """This is the consequence that matters most: it changes which agent wakes up next,
    and it makes every later promotional contact a policy violation."""
    c = customer()
    assert c.dispute_status == "none"
    effects = apply_reaction(c, Reaction.ESCALATE)
    assert c.dispute_status == "open"
    assert "dispute_opened" in effects


def test_escalating_twice_does_not_reopen_the_same_dispute():
    c = customer()
    apply_reaction(c, Reaction.ESCALATE)
    effects = apply_reaction(c, Reaction.ESCALATE)
    assert "dispute_opened" not in effects


def test_ignore_changes_nothing():
    c = customer()
    apply_reaction(c, Reaction.IGNORE)
    assert (c.converted, c.opted_out, c.irritation, c.dispute_status) == (
        False,
        False,
        0,
        "none",
    )


# ---------------------------------------------------------------- the trajectory


def test_three_messages_measurably_change_the_world():
    """Walk a customer through three contacts in one day and check the world differs."""
    engine = PersonaEngine(offline=True)
    c = customer()
    before = (c.opted_out, c.dispute_status, c.irritation)

    for n in (1, 2, 3):
        result = engine.decide(
            ctx(
                archetype=archetype_for(c.id),
                contacts_24h=n,
                contacts_total=n,
                discount_pct=5,
                dispute_open=c.dispute_status == "open",
                irritation=c.irritation,
                already_opted_out=c.opted_out,
            )
        )
        apply_reaction(c, result.reaction)

    after = (c.opted_out, c.dispute_status, c.irritation)
    assert after != before, "three messages left the world unchanged — persona is inert"
    assert c.opted_out or c.dispute_status == "open"
