"""Resend's send tool takes an ARRAY of recipients, and that changes the entity path.

Razorpay's send tools take a bare string in the same position, so assuming the shape
rather than reading the published schema would have produced a manifest that loads
cleanly, governs nothing, and reports no error: `to` would dig out `["a@b.com"]`, which
normalises to the string "['a@b.com']" and resolves to an entity nobody else ever
matches.

That is the worst kind of failure for a governance layer. Silent under-coverage looks
exactly like compliance.
"""

from __future__ import annotations

import pytest

from commons.identity.resolver import IdentityResolver, normalise
from commons.ledger.db import Ledger
from commons.semantics.manifest import derive_facts, load_manifests


@pytest.fixture
def manifest():
    found = load_manifests().get("resend")
    assert found is not None, "resend.yaml did not load"
    return found


@pytest.fixture
def resolver(tmp_path):
    led = Ledger(tmp_path / "resend.db")
    led.start_run()
    return IdentityResolver(led)


def test_send_email_is_a_promotional_contact(manifest):
    assert manifest.get("send-email").action_class == "promotional_message"


async def test_the_first_recipient_is_resolved_from_the_array(manifest, resolver):
    facts = await derive_facts(
        manifest.get("send-email"),
        {"to": ["Priya@Example.com"], "subject": "hi", "text": "hi", "from": "x@y.com"},
        resolver,
        upstream=None,
        lookup_cache={},
    )
    assert facts.entity_id is not None, "the recipient array resolved to nobody"
    assert facts.entity_ref == "priya@example.com"


async def test_it_resolves_to_the_same_person_razorpay_would(manifest, resolver):
    """The whole point: one customer across two vendors that never met."""
    known = resolver.ledger.create_entity("Priya")
    resolver.declare(known, {"email": "priya@example.com", "phone": "+919800000021"})

    facts = await derive_facts(
        manifest.get("send-email"),
        {"to": ["priya@example.com"], "subject": "s", "text": "t", "from": "x@y.com"},
        resolver,
        upstream=None,
        lookup_cache={},
    )
    assert facts.entity_id == known


def test_a_bare_array_would_not_have_normalised():
    """Why the path is to.0 and not to."""
    assert normalise("email", ["a@b.com"]) != "a@b.com"


def test_bulk_send_tools_are_left_ungoverned(manifest):
    """Attributing fifty recipients to one customer is worse than not governing them."""
    assert manifest.get("send-batch-emails") is None
    assert manifest.get("send-broadcast") is None


def test_contact_tools_are_attributed_but_consume_nothing(manifest):
    for tool in ("create-contact", "get-contact", "update-contact", "remove-contact"):
        sem = manifest.get(tool)
        assert sem is not None, f"{tool} missing"
        assert not sem.governed, f"{tool} should not consume a budget"


async def test_a_contact_tool_still_names_the_customer(manifest, resolver):
    facts = await derive_facts(
        manifest.get("create-contact"),
        {"email": "arjun@example.com", "firstName": "Arjun"},
        resolver,
        upstream=None,
        lookup_cache={},
    )
    assert facts.entity_ref == "arjun@example.com"
