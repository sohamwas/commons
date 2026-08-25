"""How separate KINDS of handle become one person.

Normalisation (Day 2) only unifies different spellings of the SAME detail. Merging a
phone with an email is a different problem, and Commons refuses to guess at it. There
are exactly two legitimate routes, and both are somebody stating a fact:

  1. the merchant declares it, from the customer list they already have
  2. a vendor asserts it by putting both handles in one call

Anything else stays two people. These tests pin that behaviour down.
"""

from __future__ import annotations

import pytest

from commons.identity.resolver import IdentityResolver
from commons.ledger.db import Ledger
from commons.semantics.manifest import MANIFEST_DIR, derive_facts, load_manifests


@pytest.fixture()
def ledger(tmp_path):
    led = Ledger(tmp_path / "link.db")
    led.start_run(mode="OBSERVE")
    yield led
    led.close()


@pytest.fixture()
def resolver(ledger):
    return IdentityResolver(ledger)


@pytest.fixture(scope="module")
def manifests():
    return load_manifests(MANIFEST_DIR)


# ------------------------------------------------- the gap, stated plainly


async def test_phone_and_email_are_two_people_until_something_links_them(
    resolver, manifests
):
    """The honest default. Nothing connects these, so Commons does not connect them."""
    whatsapp = manifests["messaging"].get("send_whatsapp")
    email_tool = manifests["messaging"].get("send_email")

    by_phone = await derive_facts(whatsapp, {"to": "9800000021"}, resolver)
    by_email = await derive_facts(email_tool, {"to": "priya@example.com"}, resolver)

    assert by_phone.entity_id != by_email.entity_id


# ------------------------------------------------- route 1: merchant declares


async def test_merchant_declaration_merges_every_handle(ledger, resolver, manifests):
    entity_id = ledger.create_entity("Priya S.")
    resolver.declare(
        entity_id,
        {"phone": "9800000021", "email": "priya@example.com", "customer_id": "cust_4471"},
    )

    whatsapp = manifests["messaging"].get("send_whatsapp")
    email_tool = manifests["messaging"].get("send_email")

    by_phone = await derive_facts(whatsapp, {"to": "+919800000021"}, resolver)
    by_email = await derive_facts(email_tool, {"to": "PRIYA@example.com"}, resolver)

    assert by_phone.entity_id == by_email.entity_id == entity_id


async def test_declaration_lets_two_agents_on_two_channels_share_a_cap(
    ledger, resolver, manifests
):
    """The reason this matters: Dispute Responder emails, Cart Recovery WhatsApps.
    Without the link they are two customers and no frequency cap can span them."""
    entity_id = ledger.create_entity("Priya S.")
    resolver.declare(entity_id, {"phone": "9800000021", "email": "priya@example.com"})

    whatsapp = manifests["messaging"].get("send_whatsapp")
    email_tool = manifests["messaging"].get("send_email")

    for agent, sem, args in (
        ("cart-recovery", whatsapp, {"to": "9800000021"}),
        ("dispute-responder", email_tool, {"to": "priya@example.com"}),
    ):
        facts = await derive_facts(sem, args, resolver)
        ledger.record_call(
            agent_id=agent,
            upstream="messaging",
            tool=sem.tool,
            action_class=facts.action_class,
            entity_id=facts.entity_id,
            forwarded=1,
        )

    contacts = ledger.count_actions(entity_id, ("promotional_message",), "1970-01-01")
    assert contacts == 2, "two channels, two agents, one person — the cap must see both"


# ------------------------------------------------- route 2: the vendor asserts it


async def test_one_razorpay_call_links_phone_and_email(ledger, resolver, manifests):
    """create_payment_link carries customer_contact AND customer_email. Razorpay is
    stating they are one customer; Commons takes it at its word."""
    link = manifests["razorpay"].get("create_payment_link")

    facts = await derive_facts(
        link,
        {
            "customer_contact": "9800000021",
            "customer_email": "Priya@example.com",
            "notes": {"discount_pct": "10"},
        },
        resolver,
    )
    assert ("email", "Priya@example.com") in facts.linked_handles

    # A later email-only contact now lands on the same person.
    email_tool = manifests["messaging"].get("send_email")
    by_email = await derive_facts(email_tool, {"to": "priya@example.com"}, resolver)
    assert by_email.entity_id == facts.entity_id

    handles = dict(ledger.identities_of(facts.entity_id))
    assert handles["phone"] == "+919800000021"
    assert handles["email"] == "priya@example.com"


async def test_conflicting_assertion_is_reported_not_silently_applied(
    ledger, resolver, manifests
):
    """Two vendors disagreeing about who someone is deserves attention, not a silent
    repoint that could hand one customer another's spending history."""
    other = ledger.create_entity("Someone Else")
    resolver.declare(other, {"email": "priya@example.com"})

    link = manifests["razorpay"].get("create_payment_link")
    facts = await derive_facts(
        link,
        {"customer_contact": "9800000021", "customer_email": "priya@example.com"},
        resolver,
    )

    assert ("email", "priya@example.com") in facts.identity_conflicts
    assert facts.entity_id != other
    # The pre-existing mapping is untouched.
    assert ledger.lookup_identity("email", "priya@example.com") == other


async def test_linking_is_idempotent(ledger, resolver, manifests):
    link = manifests["razorpay"].get("create_payment_link")
    args = {"customer_contact": "9800000021", "customer_email": "priya@example.com"}

    first = await derive_facts(link, args, resolver)
    second = await derive_facts(link, args, resolver)

    assert first.entity_id == second.entity_id
    assert first.linked_handles == [("email", "priya@example.com")]
    assert second.linked_handles == []  # already known the second time


def test_unusable_handles_are_ignored(ledger, resolver):
    entity_id = ledger.create_entity("Priya S.")
    assert resolver.link_if_new(entity_id, "phone", None) == "unusable"
    assert resolver.link_if_new(entity_id, "phone", "") == "unusable"
