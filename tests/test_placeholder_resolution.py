"""Telling Commons who an order belongs to must move that order's history.

An agent calling fetch_order(order_id="sub_4475") names an order, not a human. Commons
has to attribute the call to something, so it mints an entity keyed on the order id. On
the dashboard that reads as a customer called "sub_4475", which is nobody.

The merchant resolves it by declaring the mapping, usually an order_id column in the
customer list they import. That has to ABSORB the placeholder: the whole point is that
those calls join the real person's history, where the rules aggregate over them. Leaving
them stranded would mean a customer's own subscription spend never counted against them.
"""

from __future__ import annotations

import pytest

from commons.identity.resolver import IdentityResolver
from commons.ledger.db import Ledger

EPOCH = "2020-01-01T00:00:00.000"


@pytest.fixture
def resolver(tmp_path):
    led = Ledger(tmp_path / "placeholder.db")
    led.start_run()
    return led, IdentityResolver(led)


def _grant_on_order(ledger: Ledger, order_id: str, pct: float) -> str:
    """An agent acts on an order nobody has claimed yet."""
    entity_id = ledger.entity_for("order_id", order_id)
    ledger.record_call(
        agent_id="subscription-recovery",
        upstream="razorpay",
        tool="create_payment_link",
        action_class="discount_grant",
        entity_id=entity_id,
        magnitude=pct,
        magnitude_unit="percent",
        resource=order_id,
        decision="ALLOW",
        forwarded=1,
        is_error=0,
        sim_ts="2026-01-01T00:00:00.000",
    )
    return entity_id


def test_placeholder_is_detected(resolver):
    ledger, res = resolver
    stub = _grant_on_order(ledger, "sub_4475", 10.0)
    assert res.is_placeholder(stub)

    person = ledger.create_entity("Priya S.")
    res.declare(person, {"phone": "+919800000021"})
    assert not res.is_placeholder(person)


def test_declaring_the_owner_moves_the_history(resolver):
    ledger, res = resolver
    stub = _grant_on_order(ledger, "sub_4475", 10.0)

    person = ledger.create_entity("Priya S.")
    res.declare(person, {"phone": "+919800000021", "order_id": "sub_4475"})

    assert ledger.lookup_identity("order_id", "sub_4475") == person
    assert ledger.lookup_identity("order_id", "sub_4475") != stub
    assert ledger.sum_max_magnitude_per_resource(person, ("discount_grant",), EPOCH) == 10.0, (
        "the subscription's own spend did not follow the customer it belongs to"
    )
    assert not ledger.conn.execute(
        "SELECT 1 FROM entity WHERE id = ?", (stub,)
    ).fetchone(), "the placeholder was left behind as an unreachable duplicate"


def test_a_handle_held_by_a_real_person_is_never_stolen(resolver):
    """Two customers claiming one handle is a conflict, not a placeholder."""
    ledger, res = resolver
    first = ledger.create_entity("Priya S.")
    res.declare(first, {"phone": "+919800000021", "customer_id": "cust_1"})

    second = ledger.create_entity("Someone Else")
    res.declare(second, {"phone": "+919800000021"})

    assert ledger.lookup_identity("phone", "+919800000021") == first
    assert ledger.conn.execute("SELECT 1 FROM entity WHERE id = ?", (first,)).fetchone()
