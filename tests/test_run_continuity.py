"""Restarting the gateway must not reset what the rules aggregate over.

Every aggregation query is scoped `WHERE run_id = ?`, and the proxy used to call
start_run() on every boot. In a simulation that is correct: each experiment wants its own
isolated history. In a deployment it meant a customer given 15% yesterday could be given
15% again today because someone restarted Commons.

A run is a deployment lifetime. Simulations opt into isolation by calling start_run().
"""

from __future__ import annotations

import pytest

from commons.ledger.db import Ledger

EPOCH = "2020-01-01T00:00:00.000"


def _grant(ledger: Ledger, entity_id: str, pct: float, resource: str) -> None:
    ledger.record_call(
        agent_id="cart-recovery",
        upstream="razorpay",
        tool="create_payment_link",
        action_class="discount_grant",
        entity_id=entity_id,
        magnitude=pct,
        magnitude_unit="percent",
        resource=resource,
        decision="ALLOW",
        forwarded=1,
        is_error=0,
        sim_ts="2026-01-01T00:00:00.000",
    )


@pytest.fixture
def db(tmp_path):
    return tmp_path / "continuity.db"


def test_restart_keeps_the_discount_budget(db):
    first = Ledger(db)
    first.resume_or_start_run()
    entity = first.entity_for("phone", "+919800000001")
    _grant(first, entity, 10.0, "order_1")
    assert first.sum_max_magnitude_per_resource(entity, ("discount_grant",), EPOCH) == 10.0

    # The gateway restarts.
    second = Ledger(db)
    resumed = second.resume_or_start_run()

    assert resumed == first.run_id, "a restart opened a new run and orphaned the history"
    assert second.sum_max_magnitude_per_resource(entity, ("discount_grant",), EPOCH) == 10.0, (
        "restarting the gateway reset the customer's discount budget"
    )


def test_first_boot_opens_a_run(db):
    ledger = Ledger(db)
    run_id = ledger.resume_or_start_run()
    assert run_id and ledger.run_id == run_id


def test_ending_a_run_starts_a_fresh_one(db):
    ledger = Ledger(db)
    first = ledger.resume_or_start_run()
    ledger.end_run(first)
    assert ledger.resume_or_start_run() != first


def test_simulations_still_get_isolation(db):
    """An experiment asks for a clean slate explicitly, and gets one."""
    ledger = Ledger(db)
    ledger.resume_or_start_run()
    entity = ledger.entity_for("phone", "+919800000002")
    _grant(ledger, entity, 10.0, "order_1")

    ledger.start_run(mode="ENFORCE", notes="A/B")
    assert ledger.sum_max_magnitude_per_resource(entity, ("discount_grant",), EPOCH) == 0.0
