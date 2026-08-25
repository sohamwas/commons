"""Day 2 definition-of-done, on the live path.

Two DIFFERENT agents act on the SAME customer through Commons, against the real
Razorpay test API. Neither agent knows the other exists. The ledger does.

    .venv/Scripts/python.exe scripts/verify_ledger.py
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys

import httpx2 as httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

BASE = "http://127.0.0.1:8787"
# Two formats Razorpay itself accepts (it rejects spaces: "contact: length 8..14").
# One agent writes the full E.164 form, the other the bare Indian subscriber number —
# exactly the kind of drift you get when two vendors integrate independently.
PHONE_AS_CART_RECOVERY_WRITES_IT = "+919800000021"
PHONE_AS_SUBSCRIPTION_RECOVERY_WRITES_IT = "9800000021"


async def act(agent: str, contact: str, discount_pct: int, description: str) -> str:
    endpoint = f"{BASE}/mcp/{agent}/razorpay"
    async with httpx.AsyncClient(timeout=60.0) as hc:
        async with streamable_http_client(endpoint, http_client=hc) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                res = await session.call_tool(
                    "create_payment_link",
                    {
                        "amount": 420000,
                        "currency": "INR",
                        "description": description,
                        "customer_name": "Priya S.",
                        "customer_contact": contact,
                        "notify_sms": False,
                        "notify_email": False,
                        "notes": {"discount_pct": str(discount_pct), "order_id": "order_PRIYA_1"},
                    },
                )
                text = "".join(c.text for c in res.content if getattr(c, "type", None) == "text")
                assert not res.is_error, text[:400]
                obj = json.loads(text)
                print(f"  {agent:<24} {discount_pct:>2}% off  -> {obj.get('id')}")
                return obj.get("id", "")


def _max_call_id() -> int:
    conn = sqlite3.connect("file:commons.db?mode=ro", uri=True)
    row = conn.execute("SELECT COALESCE(MAX(id), 0) AS m FROM call").fetchone()
    conn.close()
    return int(row[0])


async def main() -> int:
    # The proxy's ledger persists across invocations; scope this check to the two calls
    # we are about to make rather than to whatever the database already holds.
    since_id = _max_call_id()

    print("two independently-built agents, same customer, different phone formatting:\n")
    await act(
        "cart-recovery",
        PHONE_AS_CART_RECOVERY_WRITES_IT,
        10,
        "Commons Day 2 - cart recovery",
    )
    await act(
        "subscription-recovery",
        PHONE_AS_SUBSCRIPTION_RECOVERY_WRITES_IT,
        8,
        "Commons Day 2 - subscription retry",
    )

    # Read the ledger the proxy just wrote.
    conn = sqlite3.connect("file:commons.db?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    print("\nledger — governed calls from this run:")
    rows = conn.execute(
        """SELECT agent_id, tool, action_class, entity_id, entity_ref, magnitude
           FROM call WHERE action_class = 'discount_grant' AND id > ? ORDER BY id""",
        (since_id,),
    ).fetchall()
    for r in rows:
        print(
            f"  {r['agent_id']:<24} {r['action_class']:<16} "
            f"{r['entity_ref']}  {r['entity_id']}  {r['magnitude']}%"
        )

    entity_ids = {r["entity_id"] for r in rows}
    print(f"\ndistinct entities touched: {len(entity_ids)}")
    assert len(entity_ids) == 1, f"cross-agent resolution FAILED — {entity_ids}"

    entity_id = entity_ids.pop()
    total = conn.execute(
        """SELECT COALESCE(SUM(magnitude), 0) AS s FROM call
           WHERE entity_id = ? AND action_class = 'discount_grant'
             AND forwarded = 1 AND id > ?""",
        (entity_id, since_id),
    ).fetchone()["s"]

    handles = conn.execute(
        "SELECT namespace, value FROM identity WHERE entity_id = ?", (entity_id,)
    ).fetchall()

    print(f"entity {entity_id} is known by: {[(h['namespace'], h['value']) for h in handles]}")
    print(f"\nCUMULATIVE DISCOUNT ACROSS ALL AGENTS: {total}%")
    print("  cart-recovery sees 10%. subscription-recovery sees 8%.")
    print("  Every per-agent dashboard is green. The customer has had 18%.")
    assert total == 18.0, f"expected 18.0, got {total}"

    print("\nDAY 2 DoD PASSED - cross-vendor entity resolution live through the proxy")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
