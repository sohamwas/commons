"""Day 3 definition-of-done.

The rule engine is a pure function of (facts, ledger), so every demo rule can be proved
here — with hand-written call sequences, no LLM, no agents, no simulator, in
milliseconds. Handoff §17.2 is the point: the claim is LOGICAL, not statistical. A unit
test with fabricated inputs still proves a bug is real.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from commons.ledger.db import Ledger
from commons.rules.engine import ENFORCE, OBSERVE, RuleEngine
from commons.rules.primitives import ALLOW, BLOCK, DEFER, EvalContext, parse_duration
from commons.semantics.manifest import CallFacts

T0 = datetime(2026, 8, 25, 9, 0, tzinfo=timezone.utc)


@pytest.fixture()
def ledger(tmp_path):
    led = Ledger(tmp_path / "rules.db")
    led.start_run(mode=OBSERVE, seed=4471)
    yield led
    led.close()


@pytest.fixture()
def engine():
    return RuleEngine.load()


@pytest.fixture()
def priya(ledger):
    return ledger.create_entity("Priya S.")


def ctx(ledger, agent: str, at: datetime = T0) -> EvalContext:
    return EvalContext(ledger=ledger, agent_id=agent, now=at, run_id=ledger.run_id)


def facts(**kw) -> CallFacts:
    kw.setdefault("governed", True)
    return CallFacts(**kw)


def happened(ledger, entity_id, *, agent, action_class, at, magnitude=None, resource=None):
    """Record something that really went through — i.e. forwarded = 1."""
    ledger.record_call(
        agent_id=agent,
        upstream="test",
        tool="t",
        action_class=action_class,
        entity_id=entity_id,
        magnitude=magnitude,
        resource=resource,
        decision=ALLOW,
        forwarded=1,
        sim_ts=at.isoformat(timespec="milliseconds"),
    )


# ---------------------------------------------------------------- durations


def test_duration_parsing():
    assert parse_duration("24h") == timedelta(hours=24)
    assert parse_duration("30d") == timedelta(days=30)
    assert parse_duration("30m") == timedelta(minutes=30)
    with pytest.raises(ValueError):
        parse_duration("soon")


# ---------------------------------------------------------------- msg_frequency


def test_frequency_allows_the_first_message(ledger, engine, priya):
    d = engine.evaluate(
        facts(action_class="promotional_message", entity_id=priya), ctx(ledger, "cart-recovery")
    )
    assert d.verdict == ALLOW


def test_frequency_defers_a_second_message_from_a_DIFFERENT_agent(ledger, engine, priya):
    """The headline case. Cart Recovery messaged 40 minutes ago; Subscription Recovery
    has no idea and is about to message again."""
    happened(
        ledger, priya, agent="cart-recovery", action_class="promotional_message",
        at=T0 - timedelta(minutes=40),
    )
    d = engine.evaluate(
        facts(action_class="promotional_message", entity_id=priya),
        ctx(ledger, "subscription-recovery"),
    )
    assert d.verdict == DEFER
    fired = [f for f in d.violations if f.rule_id == "msg_frequency"][0]
    assert fired.detail["prior_agent"] == "cart-recovery"


def test_frequency_window_expires(ledger, engine, priya):
    happened(
        ledger, priya, agent="cart-recovery", action_class="promotional_message",
        at=T0 - timedelta(hours=25),
    )
    d = engine.evaluate(
        facts(action_class="promotional_message", entity_id=priya),
        ctx(ledger, "subscription-recovery"),
    )
    assert d.verdict == ALLOW


def test_transactional_messages_are_not_capped(ledger, engine, priya):
    happened(
        ledger, priya, agent="cart-recovery", action_class="promotional_message",
        at=T0 - timedelta(minutes=10),
    )
    d = engine.evaluate(
        facts(action_class="transactional_message", entity_id=priya), ctx(ledger, "rto-shield")
    )
    assert d.verdict == ALLOW


# ---------------------------------------------------------------- discount_cap


def test_discount_under_cap_is_allowed(ledger, engine, priya):
    happened(
        ledger, priya, agent="cart-recovery", action_class="discount_grant",
        at=T0 - timedelta(days=1), magnitude=10,
    )
    d = engine.evaluate(
        facts(action_class="discount_grant", entity_id=priya, magnitude=5),
        ctx(ledger, "subscription-recovery"),
    )
    assert d.verdict == ALLOW


def test_cumulative_discount_across_agents_breaches_cap(ledger, engine, priya):
    """10% from Cart Recovery + 8% from Subscription Recovery = 18% > 15%.

    Neither individual grant is unreasonable. No per-agent check can see the sum.
    This is the arithmetic from handoff §14 and the demo video.
    """
    happened(
        ledger, priya, agent="cart-recovery", action_class="discount_grant",
        at=T0 - timedelta(minutes=40), magnitude=10,
    )
    d = engine.evaluate(
        facts(action_class="discount_grant", entity_id=priya, magnitude=8),
        ctx(ledger, "subscription-recovery"),
    )
    assert d.verdict == BLOCK
    fired = [f for f in d.violations if f.rule_id == "discount_cap"][0]
    assert fired.observed == 18.0
    assert fired.limit_value == 15.0


def test_discount_outside_window_does_not_count(ledger, engine, priya):
    happened(
        ledger, priya, agent="cart-recovery", action_class="discount_grant",
        at=T0 - timedelta(days=31), magnitude=10,
    )
    d = engine.evaluate(
        facts(action_class="discount_grant", entity_id=priya, magnitude=8),
        ctx(ledger, "subscription-recovery"),
    )
    assert d.verdict == ALLOW


# ---------------------------------------------------------------- dispute state


def test_promo_to_disputing_customer_is_blocked(ledger, engine, priya):
    ledger.set_state(priya, "dispute_status", "open")
    d = engine.evaluate(
        facts(action_class="promotional_message", entity_id=priya), ctx(ledger, "cart-recovery")
    )
    assert d.verdict == BLOCK
    assert any(f.rule_id == "no_promo_during_dispute" for f in d.violations)


def test_promo_allowed_once_dispute_closes(ledger, engine, priya):
    ledger.set_state(priya, "dispute_status", "closed")
    d = engine.evaluate(
        facts(action_class="promotional_message", entity_id=priya), ctx(ledger, "cart-recovery")
    )
    assert d.verdict == ALLOW


# ---------------------------------------------------------------- mutual exclusion


def test_second_agent_on_same_order_is_deferred(ledger, engine, priya):
    happened(
        ledger, priya, agent="cart-recovery", action_class="discount_grant",
        at=T0 - timedelta(minutes=5), magnitude=5, resource="order_X1",
    )
    d = engine.evaluate(
        facts(action_class="discount_grant", entity_id=priya, magnitude=5, resource="order_X1"),
        ctx(ledger, "rto-shield"),
    )
    assert any(f.rule_id == "one_agent_per_order" for f in d.violations)


def test_same_agent_may_continue_its_own_order(ledger, engine, priya):
    happened(
        ledger, priya, agent="cart-recovery", action_class="discount_grant",
        at=T0 - timedelta(minutes=5), magnitude=5, resource="order_X1",
    )
    d = engine.evaluate(
        facts(action_class="discount_grant", entity_id=priya, magnitude=5, resource="order_X1"),
        ctx(ledger, "cart-recovery"),
    )
    assert not any(f.rule_id == "one_agent_per_order" for f in d.violations)


def test_lease_expires(ledger, engine, priya):
    happened(
        ledger, priya, agent="cart-recovery", action_class="discount_grant",
        at=T0 - timedelta(minutes=31), magnitude=5, resource="order_X1",
    )
    d = engine.evaluate(
        facts(action_class="discount_grant", entity_id=priya, magnitude=5, resource="order_X1"),
        ctx(ledger, "rto-shield"),
    )
    assert not any(f.rule_id == "one_agent_per_order" for f in d.violations)


# ---------------------------------------------------------------- contradiction


def test_incentive_after_restriction_is_blocked(ledger, engine, priya):
    """RTO Shield restricted this customer to prepaid. Cart Recovery is still
    incentivising them. One merchant, working against itself."""
    happened(
        ledger, priya, agent="rto-shield", action_class="fulfilment_restriction",
        at=T0 - timedelta(hours=2),
    )
    d = engine.evaluate(
        facts(action_class="discount_grant", entity_id=priya, magnitude=5),
        ctx(ledger, "cart-recovery"),
    )
    assert d.verdict == BLOCK
    fired = [f for f in d.violations if f.rule_id == "restriction_beats_incentive"][0]
    assert fired.detail["winner_agent"] == "rto-shield"


def test_restriction_after_incentive_wins_and_is_recorded(ledger, engine, priya):
    """The restriction outranks the incentive, so it is ALLOWED — but the contradiction
    is still recorded, because that is the moment the timeline has to show."""
    happened(
        ledger, priya, agent="cart-recovery", action_class="discount_grant",
        at=T0 - timedelta(hours=2), magnitude=10,
    )
    d = engine.evaluate(
        facts(action_class="fulfilment_restriction", entity_id=priya), ctx(ledger, "rto-shield")
    )
    assert d.verdict == ALLOW
    override = [f for f in d.firings if f.rule_id == "restriction_beats_incentive"][0]
    assert override.detail["override"] is True
    assert override.detail["loser_agent"] == "cart-recovery"


# ---------------------------------------------------------------- engine contract


def test_all_rules_are_evaluated_not_just_the_first(ledger, engine, priya):
    """A call can be wrong in several ways at once and the merchant needs to see all
    of them — the hero UI's per-customer violation count depends on it."""
    ledger.set_state(priya, "dispute_status", "open")
    happened(
        ledger, priya, agent="cart-recovery", action_class="discount_grant",
        at=T0 - timedelta(minutes=40), magnitude=14,
    )
    d = engine.evaluate(
        facts(action_class="discount_grant", entity_id=priya, magnitude=9),
        ctx(ledger, "subscription-recovery"),
    )
    rule_ids = {f.rule_id for f in d.violations}
    assert {"discount_cap", "no_promo_during_dispute"} <= rule_ids
    assert d.verdict == BLOCK  # strictest wins


def test_ungoverned_calls_skip_evaluation(ledger, engine, priya):
    d = engine.evaluate(facts(action_class="read", governed=False, entity_id=priya), ctx(ledger, "x"))
    assert d.verdict == ALLOW
    assert d.firings == []


def test_engine_cannot_see_the_mode(ledger, engine, priya):
    """The 'one engine, two modes' claim, stated precisely.

    `evaluate()` takes no mode argument, so it is structurally incapable of deciding
    differently in simulation than it does live. Mode is applied AFTER the decision,
    when the proxy chooses whether to forward. Given identical ledger state, the
    verdict is identical by construction.
    """
    import inspect

    params = set(inspect.signature(engine.evaluate).parameters)
    assert "mode" not in params and params == {"facts", "ctx"}

    happened(
        ledger, priya, agent="cart-recovery", action_class="discount_grant",
        at=T0 - timedelta(minutes=40), magnitude=10,
    )
    call = facts(action_class="discount_grant", entity_id=priya, magnitude=8)
    first = engine.evaluate(call, ctx(ledger, "subscription-recovery"))
    second = engine.evaluate(call, ctx(ledger, "subscription-recovery"))
    assert first.verdict == second.verdict == BLOCK


def test_enforce_diverges_downstream_and_that_is_the_point(tmp_path, engine):
    """Enforcement CHANGES the future, and the A/B comparison must be honest about it.

    It would be easy — and wrong — to claim the two runs produce identical decision
    traces. They cannot: once ENFORCE stops a call, that call never consumed any budget,
    so every later decision sees a different world. That divergence IS the effect being
    demonstrated, and a sharp judge will check for it.

    Here: OBSERVE lets an over-cap discount through, so a later small discount is also
    refused. ENFORCE stops the first one, leaving room for the later one to succeed.
    """
    sequence = [
        ("cart-recovery", 10),
        ("subscription-recovery", 8),   # takes the total to 18% — over the 15% cap
        ("rto-shield", 4),
    ]

    def run(mode: str):
        led = Ledger(tmp_path / f"{mode}.db")
        led.start_run(mode=mode)
        entity = led.create_entity("Priya S.")
        verdicts = []
        for i, (agent, magnitude) in enumerate(sequence):
            at = T0 + timedelta(minutes=10 * i)
            d = engine.evaluate(
                facts(action_class="discount_grant", entity_id=entity, magnitude=magnitude),
                ctx(led, agent, at),
            )
            verdicts.append(d.verdict)
            # The ONLY behavioural difference between the modes is this line.
            forwarded = 1 if (mode == OBSERVE or not d.blocked) else 0
            led.record_call(
                agent_id=agent, upstream="test", tool="t", action_class="discount_grant",
                entity_id=entity, magnitude=magnitude, decision=d.verdict,
                forwarded=forwarded, sim_ts=at.isoformat(timespec="milliseconds"),
            )
        delivered = led.sum_magnitude(entity, ("discount_grant",), "1970-01-01")
        led.close()
        return verdicts, delivered

    observed, observed_total = run(OBSERVE)
    enforced, enforced_total = run(ENFORCE)

    # Same decision at the moment of divergence...
    assert observed[1] == enforced[1] == BLOCK
    # ...but afterwards the two worlds are genuinely different.
    assert observed[2] == BLOCK, "OBSERVE: 18% already spent, so 4% more is refused too"
    assert enforced[2] == ALLOW, "ENFORCE: only 10% was ever spent, so 4% more fits"
    assert observed != enforced

    # And enforcement did the job it exists to do.
    assert observed_total == 22.0
    assert enforced_total == 14.0
    assert enforced_total <= 15.0
