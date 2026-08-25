"""Declare the world's customers to Commons.

Without this, an agent contacting someone by email and another contacting the same
person by phone resolve to two different people, and every cross-agent rule between
them silently fails to fire. The world knows each customer's phone, email and Razorpay
id; this hands that mapping over once, the same way a merchant would sync their
customer list.
"""

from __future__ import annotations

import logging

import httpx2 as httpx

logger = logging.getLogger(__name__)


def payload_for(world) -> dict:
    return {
        "entities": [
            {
                "ref": c.id,
                "display_name": c.name,
                "handles": c.handles(),
                "state": {"dispute_status": c.dispute_status},
            }
            for c in world.customers.values()
        ]
    }


def seed_identities(world, base_url: str = "http://127.0.0.1:8787", timeout: float = 60.0) -> dict:
    """POST the population to Commons and record the assigned entity ids on the world."""
    response = httpx.post(
        f"{base_url}/admin/entities", json=payload_for(world), timeout=timeout
    )
    response.raise_for_status()
    mapping = response.json()["entities"]

    for ref, entity_id in mapping.items():
        if ref in world.customers:
            world.customers[ref].entity_id = entity_id

    logger.info("declared %d customers to Commons", len(mapping))
    return mapping
