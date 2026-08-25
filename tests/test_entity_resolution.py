"""Day 2 definition-of-done.

The single most important test in the project (plan §3): a WhatsApp message on one
vendor's server and a payment link on another vendor's server, naming the customer
differently, must resolve to the SAME entity.

That edge is what no per-agent permission system can see — neither vendor knows the
other exists, so neither can be asked "has too much already happened to this person?"
"""

from __future__ import annotations

import pytest

from commons.identity.resolver import IdentityResolver, normalise
from commons.ledger.db import Ledger
from commons.semantics.manifest import (
    MANIFEST_DIR,
    derive_facts,
    dig,
    load_manifests,
    to_number,
)


@pytest.fixture()
def ledger(tmp_path):
    led = Ledger(tmp_path / "test.db")
    led.start_run(mode="OBSERVE", seed=4471)
    yield led
    led.close()


@pytest.fixture()
def resolver(ledger):
    return IdentityResolver(ledger)


@pytest.fixture(scope="module")
def manifests():
    return load_manifests(MANIFEST_DIR)


# ---------------------------------------------------------------- normalisation


@pytest.mark.parametrize(
    "raw",
    [
        "+919800000021",
        "+91 98000 00021",
        "919800000021",
        "09800000021",
        "9800000021",
        "  +91-98000-00021  ",
    ],
)
def test_indian_phone_shapes_agree(raw):
    """Payment and messaging vendors write the same number six different ways."""
    assert normalise("phone", raw) == "+919800000021"


def test_email_case_folds():
    assert normalise("email", "  Priya@Example.COM ") == "priya@example.com"


def test_unusable_handles_are_none():
    assert normalise("phone", None) is None
    assert normalise("phone", "") is None
    assert normalise("phone", "not-a-number") is None


def test_distinct_numbers_stay_distinct():
    assert normalise("phone", "9800000021") != normalise("phone", "9800000022")


# ---------------------------------------------------------------- the core claim


async def test_cross_vendor_resolution_is_the_same_entity(ledger, resolver, manifests):
    """THE test.

    Cart Recovery sends a WhatsApp via the messaging server.
    Subscription Recovery creates a discounted payment link via Razorpay.
    Different vendors, different tools, different argument names, different phone
    formatting. One human.
    """
    whatsapp = manifests["messaging"].get("send_whatsapp")
    payment_link = manifests["razorpay"].get("create_payment_link")

    msg_facts = await derive_facts(
        whatsapp,
        {"to": "+91 98000 00021", "body": "Still interested? 10% off."},
        resolver,
    )
    link_facts = await derive_facts(
        payment_link,
        {
            "amount": 420000,
            "currency": "INR",
            "customer_contact": "919800000021",
            "notes": {"discount_pct": "8", "order_id": "order_X1"},
        },
        resolver,
    )

    assert msg_facts.entity_id is not None
    assert msg_facts.entity_id == link_facts.entity_id, (
        "cross-vendor entity resolution failed — the thesis depends on this join"
    )
    assert msg_facts.entity_ref == link_facts.entity_ref == "+919800000021"


async def test_declared_identity_folds_all_namespaces(ledger, resolver, manifests):
    """The merchant declares once that one customer owns a phone, an email and a
    Razorpay customer_id. Every namespace then resolves to the same entity."""
    entity_id = ledger.create_entity("Priya S.")
    resolver.declare(
        entity_id,
        {"phone": "9800000021", "email": "Priya@example.com", "customer_id": "cust_4471"},
    )

    whatsapp = manifests["messaging"].get("send_whatsapp")
    email_tool = manifests["messaging"].get("send_email")

    via_phone = await derive_facts(whatsapp, {"to": "+919800000021"}, resolver)
    via_email = await derive_facts(email_tool, {"to": "priya@EXAMPLE.com"}, resolver)

    assert via_phone.entity_id == entity_id
    assert via_email.entity_id == entity_id
    assert len(ledger.identities_of(entity_id)) == 3


# ---------------------------------------------------------------- semantics


async def test_discount_magnitude_is_extracted(resolver, manifests):
    """The discount is what consumes the shared margin budget, so it must come out
    of an arbitrary tool call as a number."""
    sem = manifests["razorpay"].get("create_payment_link")
    facts = await derive_facts(
        sem,
        {"customer_contact": "9800000021", "notes": {"discount_pct": "10"}},
        resolver,
    )
    assert facts.action_class == "discount_grant"
    assert facts.magnitude == 10.0
    assert facts.magnitude_unit == "percent"
    assert facts.governed is True


async def test_transactional_messages_are_reclassified(resolver, manifests):
    """A shipping update is not a marketing touch; frequency caps apply to the latter."""
    sem = manifests["messaging"].get("send_whatsapp")

    promo = await derive_facts(sem, {"to": "9800000021"}, resolver)
    txn = await derive_facts(sem, {"to": "9800000021", "kind": "transactional"}, resolver)

    assert promo.action_class == "promotional_message"
    assert txn.action_class == "transactional_message"


async def test_reads_are_not_governed(resolver, manifests):
    sem = manifests["razorpay"].get("fetch_payment")
    facts = await derive_facts(sem, {"payment_id": "pay_1"}, resolver)
    assert facts.governed is False
    assert facts.entity_id is None


async def test_resource_extracted_for_mutual_exclusion(resolver, manifests):
    """One agent per order requires knowing which order a call touches."""
    sem = manifests["razorpay"].get("create_payment_link")
    facts = await derive_facts(
        sem,
        {"customer_contact": "9800000021", "notes": {"order_id": "order_X1"}},
        resolver,
    )
    assert facts.resource == "order_X1"


# ---------------------------------------------------------------- helpers


def test_dig_walks_json_encoded_strings():
    """Razorpay's `notes` comes back as a JSON string often enough to matter."""
    assert dig({"notes": '{"discount_pct": 12}'}, "notes.discount_pct") == 12
    assert dig({"a": {"b": {"c": 7}}}, "a.b.c") == 7
    assert dig({"a": 1}, "a.b.c") is None
    assert dig({}, "") is None


def test_to_number_tolerates_vendor_formatting():
    assert to_number("10") == 10.0
    assert to_number("10%") == 10.0
    assert to_number(12) == 12.0
    assert to_number("abc") is None
    assert to_number(None) is None


# ---------------------------------------------------------------- ledger wiring


async def test_ledger_records_calls_against_the_entity(ledger, resolver, manifests):
    """Two agents, two vendors, one entity — and the ledger can already answer the
    question least privilege cannot: how much has happened to this person?"""
    entity_id = ledger.create_entity("Priya S.")
    resolver.declare(entity_id, {"phone": "9800000021"})

    link = manifests["razorpay"].get("create_payment_link")
    for agent, pct in (("cart-recovery", 10), ("subscription-recovery", 8)):
        facts = await derive_facts(
            link,
            {"customer_contact": "9800000021", "notes": {"discount_pct": pct}},
            resolver,
        )
        ledger.record_call(
            agent_id=agent,
            upstream="razorpay",
            tool="create_payment_link",
            action_class=facts.action_class,
            entity_id=facts.entity_id,
            entity_ref=facts.entity_ref,
            magnitude=facts.magnitude,
            magnitude_unit=facts.magnitude_unit,
            forwarded=1,
        )

    total = ledger.sum_magnitude(entity_id, ("discount_grant",), since_iso="1970-01-01")
    assert total == 18.0, "cumulative cross-agent discount not visible in the ledger"
