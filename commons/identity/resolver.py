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

    def resolve_existing(self, namespace: str, raw: object) -> tuple[str | None, str | None]:
        """Look a handle up WITHOUT creating an entity for it."""
        value = normalise(namespace, raw)
        if value is None:
            return None, None
        return self.ledger.lookup_identity(namespace, value), value

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

    def existing_for(self, handles: dict[str, object]) -> set[str]:
        """Which entities do these handles already point at? Creates nothing.

        Re-importing the same customer list is normal: a merchant syncs, adds a column,
        syncs again. Without this the importer minted a fresh entity every time and
        repointed the handles onto it, leaving the previous one behind with no handles
        and no way to reach it.
        """
        found: set[str] = set()
        for namespace, raw in handles.items():
            value = normalise(namespace, raw)
            if value is None:
                continue
            existing = self.ledger.lookup_identity(namespace, value)
            if existing:
                found.add(existing)
        return found

    def is_placeholder(self, entity_id: str) -> bool:
        """True if nothing about this entity identifies a person.

        An agent calling fetch_order(order_id=…) names an order, not a human. Commons has
        to attribute that call to something, so it mints an entity keyed on the order id.
        It is a real record with real activity, and it is nobody until the merchant says
        whose order it was.
        """
        return not any(
            namespace in (PHONE, EMAIL, CUSTOMER_ID)
            for namespace, _ in self.ledger.identities_of(entity_id)
        )

    def declare(self, entity_id: str, handles: dict[str, object], source: str = "declared") -> None:
        """Seed the graph: one entity owning several vendor handles.

        The world simulator calls this once per customer, which is the declarative
        mapping the merchant would supply in production.

        Declaring a handle that currently belongs to a PLACEHOLDER absorbs it. Saying
        "order_9001 is Priya" is the answer to a question Commons could not answer on its
        own, so Priya inherits that order's history instead of it being stranded on a
        record nobody can reach. A handle held by an identified person is left alone and
        reported: that is two customers in conflict, not a placeholder being resolved.
        """
        for namespace, raw in handles.items():
            value = normalise(namespace, raw)
            if value is None:
                continue

            holder = self.ledger.lookup_identity(namespace, value)
            if holder and holder != entity_id:
                if self.is_placeholder(holder):
                    logger.info(
                        "absorbing placeholder %s into %s via %s=%s",
                        holder, entity_id, namespace, value,
                    )
                    self.ledger.absorb(entity_id, holder)
                else:
                    logger.warning(
                        "identity conflict: %s=%s belongs to %s, not %s — keeping existing",
                        namespace, value, holder, entity_id,
                    )
                    continue

            self.ledger.link_identity(namespace, value, entity_id, source=source)
