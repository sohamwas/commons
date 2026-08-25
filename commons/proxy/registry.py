"""The agent registry and per-agent tool allowlists.

ANTI-CIRCULARITY (handoff §12, §17.5) — READ BEFORE EDITING:
    These four agents are built to Razorpay's OWN published job descriptions.
    They are NOT designed to collide. Collisions in the simulation come from the
    customer population (sampled for concurrent conditions, handoff §16.5), never
    from these definitions. Do not add a tool or widen a scope to manufacture a
    conflict — doing so destroys the finding the project exists to demonstrate.

The allowlists are also handoff §16.3 in practice: Razorpay's remote MCP exposes 42
tools; each agent sees 3–4. That is a ~5x system-prompt token saving, and it is plain
least privilege — the principle Commons complements rather than replaces.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentSpec:
    id: str
    display_name: str
    # upstream name -> tools this agent may call on it
    tools: dict[str, tuple[str, ...]]

    def allowed(self, upstream: str) -> tuple[str, ...]:
        return self.tools.get(upstream, ())


AGENTS: dict[str, AgentSpec] = {
    "cart-recovery": AgentSpec(
        id="cart-recovery",
        display_name="Cart Recovery",
        tools={
            "razorpay": ("create_payment_link", "payment_link_notify", "fetch_all_payments"),
            "messaging": ("send_whatsapp",),
        },
    ),
    "subscription-recovery": AgentSpec(
        id="subscription-recovery",
        display_name="Subscription Recovery",
        tools={
            "razorpay": ("create_payment_link", "payment_link_notify", "fetch_order"),
            "messaging": ("send_whatsapp",),
        },
    ),
    "dispute-responder": AgentSpec(
        id="dispute-responder",
        display_name="Dispute Responder",
        tools={
            # NOTE: create_refund is NOT exposed by Razorpay's remote MCP (42 of 55 tools).
            # None of the four demo rules need it — see IMPLEMENTATION_PLAN.md §7 R1.
            "razorpay": ("fetch_payment", "fetch_refund", "fetch_specific_refund_for_payment"),
            "messaging": ("send_email",),
        },
    ),
    "rto-shield": AgentSpec(
        id="rto-shield",
        display_name="RTO Shield",
        tools={
            "razorpay": ("fetch_order", "update_order", "fetch_all_orders"),
            "messaging": ("send_whatsapp",),
        },
    ),
}


def get_agent(agent_id: str) -> AgentSpec | None:
    return AGENTS.get(agent_id)
