"""Day 4 definition-of-done: the world is seeded, reproducible, and calibrated.

Determinism is doing double duty (handoff §15.3): it makes the OBSERVE/ENFORCE
comparison exact, and it is what allows a recorded run to be shipped as JSON and
replayed on a static site with no backend.
"""

from __future__ import annotations

import json
from datetime import timedelta

from commons.world.customers import (
    CART_ABANDONMENT_RATE,
    COD_RTO_RATE,
    DISPUTE_RATE,
    UPI_AUTOPAY_SUCCESS_RATE,
)
from commons.world.events import EventType
from commons.world.world import build_world


def fingerprint(events) -> str:
    """A byte-for-byte signature of a generated timeline."""
    return json.dumps(
        [
            [e.at.isoformat(), e.seq, str(e.type), e.customer_id, e.payload]
            for e in events
        ],
        sort_keys=True,
    )


# ---------------------------------------------------------------- determinism


def test_same_seed_gives_a_byte_identical_world():
    a = fingerprint(build_world(seed=4471).generate())
    b = fingerprint(build_world(seed=4471).generate())
    assert a == b


def test_different_seeds_give_different_worlds():
    a = fingerprint(build_world(seed=4471).generate())
    b = fingerprint(build_world(seed=9999).generate())
    assert a != b


def test_population_is_reproducible_too():
    w1, w2 = build_world(seed=4471), build_world(seed=4471)
    w1.generate()
    w2.generate()
    assert [c.id for c in w1.customers.values()] == [c.id for c in w2.customers.values()]
    assert [c.conditions for c in w1.customers.values()] == [
        c.conditions for c in w2.customers.values()
    ]


def test_events_come_out_in_chronological_order():
    events = build_world(seed=4471).generate()
    assert events == sorted(events, key=lambda e: (e.at, e.seq))


# ---------------------------------------------------------------- shape of the world


def test_every_event_routes_to_one_of_the_four_agents():
    events = build_world(seed=4471).generate()
    agents = {e.type.agent for e in events}
    assert agents <= {
        "cart-recovery",
        "subscription-recovery",
        "dispute-responder",
        "rto-shield",
    }
    assert None not in agents


def test_overlap_is_reported_honestly():
    """The sampling rate must be disclosed, not hidden (handoff §16.5)."""
    world = build_world(seed=4471, n_customers=20, overlap_rate=0.6)
    world.generate()
    summary = world.summary()

    counted = sum(1 for c in world.customers.values() if c.concurrent_condition_count >= 2)
    assert summary["customers_with_2plus_conditions"] == counted
    assert summary["overlap_rate_configured"] == 0.6
    assert 0 < summary["share_with_2plus_conditions"] <= 1.0


def test_demo_customer_has_all_four_conditions():
    """cust_4471 (Priya) is the worked example in the video and the hero screen."""
    world = build_world(seed=4471)
    world.generate()
    priya = world.customers["cust_4471"]
    assert priya.name.startswith("Priya")
    assert set(priya.conditions) == {
        "abandoned_cart",
        "failing_mandate",
        "dispute",
        "rto_risk",
    }


def test_clustered_customers_have_events_within_days_not_weeks():
    """A shared root cause produces correlated events. Without this the 24h frequency
    rule could never fire, and the run would prove nothing."""
    events = build_world(seed=4471).generate()
    priya = [e for e in events if e.customer_id == "cust_4471"]
    assert len(priya) == 4
    span = max(e.at for e in priya) - min(e.at for e in priya)
    assert span <= timedelta(days=4), f"Priya's events span {span}, too far apart to collide"


def test_cart_and_mandate_land_within_the_frequency_window():
    """The headline collision: two agents woken by two events inside 24 hours."""
    events = build_world(seed=4471).generate()
    by_type = {e.type: e.at for e in events if e.customer_id == "cust_4471"}
    gap = abs(by_type[EventType.MANDATE_FAILED] - by_type[EventType.CART_ABANDONED])
    assert gap < timedelta(hours=24)


def test_low_overlap_world_produces_fewer_multi_condition_customers():
    low = build_world(seed=4471, overlap_rate=0.0)
    high = build_world(seed=4471, overlap_rate=1.0)
    low.generate()
    high.generate()
    assert (
        low.summary()["customers_with_2plus_conditions"]
        < high.summary()["customers_with_2plus_conditions"]
    )


# ---------------------------------------------------------------- calibration


def test_calibration_constants_match_published_figures():
    """These are cited in the README; if someone edits them, the citation breaks."""
    assert CART_ABANDONMENT_RATE == 0.70          # Baymard meta-analysis of 49 studies
    assert UPI_AUTOPAY_SUCCESS_RATE == 0.40       # published 30-50% band, midpoint
    assert COD_RTO_RATE == 0.27                   # Indian COD RTO widely reported 25-30%
    assert DISPUTE_RATE == 0.008                  # disputes are well under 1%


def test_scaling_the_population_scales_the_events():
    small = build_world(seed=4471, n_customers=5).generate()
    large = build_world(seed=4471, n_customers=40).generate()
    assert len(large) > len(small)
