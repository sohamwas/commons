"""The synthetic customer population.

We simulate the WORLD, not the system under test (handoff §17.1). The agents are real
LLM agents making real decisions, Razorpay's MCP server and test API are real, and the
tool calls are real. What is synthetic is who the customers are and what happens to them.

The population is deliberately SAMPLED FOR CONCURRENT CONDITIONS (handoff §16.5): real
merchants have thousands of customers of whom a small fraction have several things going
on at once. Twenty customers chosen at random would almost never collide, and the run
would prove nothing. So the sampler oversamples that tail on purpose, and
`overlap_rate` is reported in every run summary so the number is never hidden.

What is NOT done: the agents are not designed to collide (handoff §12, §17.5). Collisions
come from customers having concurrent conditions, never from agent instructions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# ---------------------------------------------------------------------------------
# Calibration. Every constant is a published figure with its source, so the world is
# a calibrated one rather than an invented one (handoff §10, §17.3).
# ---------------------------------------------------------------------------------

# Baymard Institute, meta-analysis of 49 studies: ~70% average documented cart abandonment.
CART_ABANDONMENT_RATE = 0.70

# UPI Autopay mandate execution success runs ~30-50% (handoff §2/§10; Razorpay's own
# Subscription Recovery agent exists because of it). We take the midpoint and model the
# failure side, which is what triggers Subscription Recovery.
UPI_AUTOPAY_SUCCESS_RATE = 0.40
UPI_AUTOPAY_FAILURE_RATE = 1.0 - UPI_AUTOPAY_SUCCESS_RATE

# Indian COD return-to-origin rates are widely reported in the 25-30% band.
COD_RTO_RATE = 0.27

# Share of Indian e-commerce orders paid cash-on-delivery. RTO risk only applies to these.
COD_SHARE = 0.35

# Payment disputes/chargebacks are rare in absolute terms (well under 1% of transactions).
DISPUTE_RATE = 0.008


@dataclass
class Customer:
    """One human, with the state that agents mutate and rules read."""

    id: str
    name: str
    phone: str
    email: str

    # Canonical entity id, assigned when the world declares identities to Commons.
    entity_id: str | None = None

    # --- conditions that make an agent want to act ---
    has_abandoned_cart: bool = False
    cart_value_paise: int = 0
    subscription_active: bool = False
    mandate_will_fail: bool = False
    pays_cod: bool = False
    high_rto_risk: bool = False
    will_dispute: bool = False

    # --- mutable state, updated as the run proceeds ---
    dispute_status: str = "none"          # none | open | closed
    lifetime_discount_pct: float = 0.0
    contacts: list[datetime] = field(default_factory=list)
    opted_out: bool = False
    irritation: int = 0                   # rises with unwanted contact (Day 5)
    converted: bool = False
    order_id: str | None = None

    @property
    def conditions(self) -> list[str]:
        """The concurrent conditions this customer has — what makes agents converge."""
        active = []
        if self.has_abandoned_cart:
            active.append("abandoned_cart")
        if self.subscription_active and self.mandate_will_fail:
            active.append("failing_mandate")
        if self.will_dispute:
            active.append("dispute")
        if self.pays_cod and self.high_rto_risk:
            active.append("rto_risk")
        return active

    @property
    def concurrent_condition_count(self) -> int:
        return len(self.conditions)

    def handles(self) -> dict[str, str]:
        """What the different vendors know this person by. Declared to Commons once.

        `order_id` is included because a merchant genuinely knows which order belongs to
        which customer. Without it, a tool like update_order — which names only an order
        — resolves to nobody, and rules about the customer behind that order cannot fire.
        """
        handles = {"phone": self.phone, "email": self.email, "customer_id": self.id}
        if self.order_id:
            handles["order_id"] = self.order_id
        return handles
