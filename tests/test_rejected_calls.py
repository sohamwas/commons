"""A call the vendor refused must not consume the customer's budget.

Found by running examples/loyalty_agent.py against the live proxy. Razorpay's test mode
caps payment links at 30, so three create_payment_link calls came back as errors. Commons
had already recorded them as discount_grants with a magnitude, and every aggregation query
filtered only on `forwarded = 1` — so discounts nobody ever received were consuming real
budget, and a later legitimate offer would have been blocked because of them.

The same bug silences a customer for 24 hours over a WhatsApp message the vendor bounced.

`is_error = 1` is unambiguous here: it means the vendor answered and said no. A timeout
raises inside Upstream.call_tool before `forwarded` is ever set to 1, so those rows are
already excluded and never reach this condition.
"""

from __future__ import annotations

import pytest

from commons.ledger.db import Ledger

EPOCH = "2020-01-01T00:00:00.000"


def _call(ledger: Ledger, entity_id: str, **over):
    fields = dict(
        agent_id="agent-a",
        upstream="razorpay",
        tool="create_payment_link",
        action_class="discount_grant",
        entity_id=entity_id,
        magnitude=10.0,
        magnitude_unit="percent",
        decision="ALLOW",
        forwarded=1,
        is_error=0,
        sim_ts="2026-01-01T00:00:00.000",
    )
    fields.update(over)
    return ledger.record_call(**fields)


@pytest.fixture
def ledger(tmp_path):
    led = Ledger(tmp_path / "t.db")
    led.start_run()
    return led


def test_rejected_grant_does_not_consume_budget(ledger):
    entity = ledger.entity_for("phone", "+919800000001")
    _call(ledger, entity, resource="order_1")                   # accepted
    _call(ledger, entity, resource="order_2", is_error=1)       # vendor refused

    total = ledger.sum_max_magnitude_per_resource(
        entity, ("discount_grant",), EPOCH
    )
    assert total == 10.0, "a payment link the vendor rejected consumed real discount budget"


def test_rejected_message_does_not_consume_a_frequency_slot(ledger):
    entity = ledger.entity_for("phone", "+919800000002")
    _call(ledger, entity, tool="send_whatsapp", action_class="promotional_message",
          magnitude=None, is_error=1)

    assert ledger.count_actions(entity, ("promotional_message",), EPOCH) == 0, (
        "a bounced message silenced the customer for the whole window"
    )


def test_rejected_call_does_not_hold_a_mutual_exclusion_lease(ledger):
    entity = ledger.entity_for("order_id", "order_9")
    _call(ledger, entity, tool="update_order", action_class="fulfilment_restriction",
          magnitude=None, resource="order_9", is_error=1)

    assert ledger.last_actor_on_resource("order_9", EPOCH) is None, (
        "a failed call locked the order against every other agent"
    )


def test_rejected_call_does_not_win_a_contradiction(ledger):
    entity = ledger.entity_for("phone", "+919800000003")
    _call(ledger, entity, tool="update_order", action_class="fulfilment_restriction",
          magnitude=None, is_error=1)

    assert ledger.last_action_of_class(entity, "fulfilment_restriction", EPOCH) is None


def test_accepted_calls_still_count(ledger):
    """The fix must not swing the other way and let real spend through."""
    entity = ledger.entity_for("phone", "+919800000004")
    _call(ledger, entity, resource="order_1", magnitude=10.0)
    _call(ledger, entity, resource="order_2", magnitude=8.0)

    assert ledger.sum_max_magnitude_per_resource(entity, ("discount_grant",), EPOCH) == 18.0
    assert ledger.count_actions(entity, ("discount_grant",), EPOCH) == 2
