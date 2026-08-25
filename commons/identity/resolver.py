"""Entity resolution — the core technical contribution (plan §3).

The hard part is not joining two Razorpay calls; inside one vendor everything already
carries a customer_id. The hard part is recognising that

    messaging.send_whatsapp(to: "+91 98000 00021")
    razorpay.create_payment_link(customer.contact: "919800000021")

are the same human, when the two servers were built by parties who have never heard of
each other. Normalisation is what makes that join possible, and it is the only place
Commons is allowed to be clever — everything downstream is plain SQL.

Mappings are DECLARED, never inferred (handoff §11, plan D4): the merchant states once
per server which argument carries which kind of handle. Commons only normalises.
"""

from __future__ import annotations

import logging
import re

import phonenumbers

logger = logging.getLogger(__name__)

DEFAULT_REGION = "IN"

PHONE = "phone"
EMAIL = "email"
CUSTOMER_ID = "customer_id"
ORDER_ID = "order_id"


def normalise(namespace: str, raw: object) -> str | None:
    """Fold a vendor-visible handle into a canonical form. None if unusable."""
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None

    if namespace == PHONE:
        return _normalise_phone(value)
    if namespace == EMAIL:
        return value.lower()
    # Opaque vendor identifiers: trim only. Case is significant in Razorpay ids.
    return value


def _normalise_phone(value: str) -> str | None:
    """E.164, so "+91 98000 00021", "919800000021" and "09800000021" agree.

    Indian numbers arrive in all three shapes across payment and messaging vendors,
    which is exactly the join that per-agent systems never get to make.
    """
    try:
        parsed = phonenumbers.parse(value, DEFAULT_REGION)
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException:
        pass

    # Fall back to digits-only so an unparseable-but-consistent handle still joins
    # with itself rather than fragmenting into several entities.
    digits = re.sub(r"\D", "", value)
    if not digits:
        return None
    if len(digits) == 10:  # bare Indian subscriber number
        return f"+91{digits}"
    if len(digits) > 10 and not digits.startswith("0"):
        return f"+{digits}"
    return f"+{digits.lstrip('0')}" if digits.lstrip("0") else None


class IdentityResolver:
    """Resolves normalised handles to canonical entity ids, via the ledger's identity graph."""

    def __init__(self, ledger) -> None:
        self.ledger = ledger

    def resolve(self, namespace: str, raw: object, source: str = "") -> tuple[str | None, str | None]:
        """Return (entity_id, normalised_value). Creates the entity if the handle is new."""
        value = normalise(namespace, raw)
        if value is None:
            return None, None
        entity_id = self.ledger.entity_for(namespace, value, source=source)
        return entity_id, value

    def link_if_new(
        self, entity_id: str, namespace: str, raw: object, source: str = "vendor-asserted"
    ) -> str:
        """Attach an extra handle that a vendor asserted belongs to this entity.

        When Razorpay receives create_payment_link(customer_contact=…, customer_email=…),
        the vendor is stating in one breath that this phone and this email are the same
        customer. Recording that is taking the vendor at its word, not inferring — which
        is the line this project refuses to cross (handoff §11).

        A handle already pointing at a DIFFERENT entity is left alone and reported. Two
        vendors disagreeing about who someone is deserves a merchant's attention, not a
        silent repoint that could hand one customer another's spending history.
        """
        value = normalise(namespace, raw)
        if value is None:
            return "unusable"

        existing = self.ledger.lookup_identity(namespace, value)
        if existing is None:
            self.ledger.link_identity(namespace, value, entity_id, source=source)
            logger.info("linked %s=%s -> %s (%s)", namespace, value, entity_id, source)
            return "linked"
        if existing == entity_id:
            return "already-known"

        logger.warning(
            "identity conflict: %s=%s is already %s, but %s asserts %s — keeping existing",
            namespace,
            value,
            existing,
            source,
            entity_id,
        )
        return "conflict"

    def declare(self, entity_id: str, handles: dict[str, object], source: str = "declared") -> None:
        """Seed the graph: one entity owning several vendor handles.

        The world simulator calls this once per customer, which is the declarative
        mapping the merchant would supply in production.
        """
        for namespace, raw in handles.items():
            value = normalise(namespace, raw)
            if value is None:
                continue
            self.ledger.link_identity(namespace, value, entity_id, source=source)
