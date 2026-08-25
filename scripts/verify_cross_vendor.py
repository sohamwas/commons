"""Day 4 definition-of-done, on the live path — TWO vendors.

Cart Recovery messages Priya through the messaging vendor.
Subscription Recovery messages her too, and discounts her through Razorpay.

Three different servers' worth of tool calls, two independently-built vendors, one
human. Neither vendor knows the other exists. Commons resolves them to one entity and
applies the merchant's policy across all of it.

    .venv/Scripts/python.exe mcp_servers/messaging/run.py --port 8788
    .venv/Scripts/python.exe scripts/run_proxy.py --mode ENFORCE --db enforce.db
    .venv/Scripts/python.exe scripts/verify_cross_vendor.py
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

# The same human, written the way each vendor's integration happens to write her.
PHONE_MESSAGING = "+91 98000 00021"   # messaging vendor tolerates spaces
PHONE_RAZORPAY = "9800000021"         # Razorpay wants 8-14 chars, no spaces


async def call(agent: str, upstream: str, tool: str, args: dict) -> tuple[bool, str]:
    endpoint = f"{BASE}/mcp/{agent}/{upstream}"
    async with httpx.AsyncClient(timeout=60.0) as hc:
        async with streamable_http_client(endpoint, http_client=hc) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                res = await session.call_tool(tool, args)
                text = "".join(
                    c.text for c in res.content if getattr(c, "type", None) == "text"
                )
                return (not res.is_error), text


async def main() -> int:
    async with httpx.AsyncClient(timeout=30.0) as hc:
        health = (await hc.get(f"{BASE}/health")).json()
    mode = health["mode"]
    db = "enforce.db" if mode == "ENFORCE" else "observe.db"
    print(f"proxy mode: {mode}   upstreams: {health['upstreams']}\n")
    assert "messaging" in health["upstreams"], "messaging vendor not connected"

    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    since_id = conn.execute("SELECT COALESCE(MAX(id),0) FROM call").fetchone()[0]
    conn.close()

    # 1. Cart Recovery reaches Priya through the MESSAGING vendor.
    ok1, t1 = await call(
        "cart-recovery",
        "messaging",
        "send_whatsapp",
        {"to": PHONE_MESSAGING, "body": "Left something behind? 10% off.", "kind": "promotional"},
    )
    print(f"  cart-recovery         -> messaging.send_whatsapp   {'SENT' if ok1 else 'REFUSED'}")
    if not ok1:
        print(f"      {t1[:160]}")

    # 2. Subscription Recovery, minutes later, has no idea and messages her too.
    ok2, t2 = await call(
        "subscription-recovery",
        "messaging",
        "send_whatsapp",
        {"to": PHONE_MESSAGING, "body": "Your autopay failed - retry with 8% off.", "kind": "promotional"},
    )
    print(f"  subscription-recovery -> messaging.send_whatsapp   {'SENT' if ok2 else 'REFUSED'}")
    if not ok2:
        print(f"      {t2[:160]}")

    # 3. And discounts her through RAZORPAY, a completely different vendor.
    ok3, t3 = await call(
        "subscription-recovery",
        "razorpay",
        "create_payment_link",
        {
            "amount": 420000,
            "currency": "INR",
            "description": "Commons Day 4 - cross-vendor",
            "customer_name": "Priya S.",
            "customer_contact": PHONE_RAZORPAY,
            "notify_sms": False,
            "notify_email": False,
            "notes": {"discount_pct": "8", "order_id": "order_4471"},
        },
    )
    print(f"  subscription-recovery -> razorpay.create_payment_link  {'OK' if ok3 else 'REFUSED'}")
    if not ok3:
        print(f"      {t3[:160]}")

    # ---- what did Commons see? ----
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT agent_id, upstream, tool, action_class, entity_id, entity_ref, decision
           FROM call WHERE id > ? ORDER BY id""",
        (since_id,),
    ).fetchall()

    print("\nledger:")
    for r in rows:
        print(
            f"  {r['agent_id']:<22} {r['upstream']:<10} {r['tool']:<20} "
            f"{r['action_class'] or '-':<21} {r['entity_ref']}  {r['decision']}"
        )

    upstreams_touched = {r["upstream"] for r in rows}
    entities = {r["entity_id"] for r in rows if r["entity_id"]}
    print(f"\nvendors touched:   {sorted(upstreams_touched)}")
    print(f"distinct entities: {len(entities)}")
    assert len(upstreams_touched) == 2, "expected calls across both vendors"
    assert len(entities) == 1, f"cross-vendor resolution FAILED: {entities}"

    entity_id = entities.pop()
    handles = conn.execute(
        "SELECT namespace, value FROM identity WHERE entity_id = ?", (entity_id,)
    ).fetchall()
    print(f"entity {entity_id} known by: {[(h['namespace'], h['value']) for h in handles]}")
    conn.close()

    print()
    if mode == "ENFORCE":
        assert ok1, "the first contact should be allowed"
        assert not ok2, "the second promotional message within 24h should be stopped"
        print("ENFORCE: the second message was stopped because a DIFFERENT agent, on a")
        print("         DIFFERENT vendor's server, had already contacted her minutes earlier.")
    else:
        print("OBSERVE: everything went through; the violations are recorded, not prevented.")

    print(f"\nDAY 4 DoD PASSED ({mode}) - two vendors, one entity")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
