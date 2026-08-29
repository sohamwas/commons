"""Importing a customer list twice must not duplicate the customer.

A merchant syncs, adds a column, syncs again. The importer used to mint a fresh entity
for every row on every import and repoint the handles onto it, leaving the previous
entity stranded with no handles. The person then had a duplicate per import, and the
history the rules aggregate over stopped following them.
"""

from __future__ import annotations

import pytest

from commons.identity.resolver import IdentityResolver
from commons.ledger.db import Ledger

ROW = {
    "ref": "cust_9001",
    "display_name": "Priya Nair",
    "handles": {
        "customer_id": "cust_9001",
        "phone": "+91 99000 10001",
        "email": "priya.nair@example.com",
    },
}


@pytest.fixture
def resolver(tmp_path):
    return IdentityResolver(Ledger(tmp_path / "import.db"))


def _import(resolver: IdentityResolver, row: dict) -> str:
    """The seed_entities decision, in isolation."""
    known = resolver.existing_for(row["handles"])
    entity_id = known.pop() if len(known) == 1 else resolver.ledger.create_entity(row["display_name"])
    resolver.declare(entity_id, row["handles"])
    return entity_id


def test_reimport_reuses_the_same_customer(resolver):
    first = _import(resolver, ROW)
    second = _import(resolver, ROW)
    assert first == second, "importing the same list twice created a duplicate customer"


def test_reimport_with_a_new_handle_extends_the_same_customer(resolver):
    first = _import(resolver, ROW)

    # The merchant adds an order id column and syncs again.
    grown = {**ROW, "handles": {**ROW["handles"], "order_id": "order_9001"}}
    assert _import(resolver, grown) == first

    handles = dict(resolver.ledger.identities_of(first))
    assert handles["order_id"] == "order_9001"
    assert handles["phone"] == "+919900010001"


def test_messy_phone_formats_resolve_to_one_customer(resolver):
    """The formats a real export mixes are one detail written several ways."""
    first = _import(resolver, ROW)
    for spelling in ("9900010001", "09900010001", "+919900010001", "99000-10001"):
        assert _import(resolver, {**ROW, "handles": {"phone": spelling}}) == first


def test_a_genuinely_new_customer_is_created(resolver):
    first = _import(resolver, ROW)
    other = _import(
        resolver,
        {
            "ref": "cust_9002",
            "display_name": "Arjun Rao",
            "handles": {"customer_id": "cust_9002", "phone": "9900010002"},
        },
    )
    assert other != first
