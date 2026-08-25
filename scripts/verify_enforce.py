"""Day 3 definition-of-done, on the live path.

Four agents act on one customer through Commons, against the real Razorpay test API.
Run this against a proxy started in OBSERVE and then in ENFORCE and compare.

    .venv/Scripts/python.exe scripts/run_proxy.py --mode OBSERVE --db observe.db
    .venv/Scripts/python.exe scripts/verify_enforce.py

    .venv/Scripts/python.exe scripts/run_proxy.py --mode ENFORCE --db enforce.db
    .venv/Scripts/python.exe scripts/verify_enforce.py
"""

from __future__ import annotations

import asyncio
import json
import sys

import httpx2 as httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

BASE = "http://127.0.0.1:8787"
PHONE = "+919800000021"
ORDER = "order_PRIYA_DAY3"


async def call(agent: str, tool: str, args: dict) -> tuple[bool, str]:
    endpoint = f"{BASE}/mcp/{agent}/razorpay"
    async with httpx.AsyncClient(timeout=60.0) as hc:
        async with streamable_http_client(endpoint, http_client=hc) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                res = await session.call_tool(tool, args)
                text = "".join(
                    c.text for c in res.content if getattr(c, "type", None) == "text"
                )
                return (not res.is_error), text


def link_args(discount_pct: int, description: str) -> dict:
    return {
        "amount": 420000,
        "currency": "INR",
        "description": description,
        "customer_name": "Priya S.",
        "customer_contact": PHONE,
        "notify_sms": False,
        "notify_email": False,
        "notes": {"discount_pct": str(discount_pct), "order_id": ORDER},
    }


async def main() -> int:
    async with httpx.AsyncClient(timeout=30.0) as hc:
        health = (await hc.get(f"{BASE}/health")).json()
    mode = health["mode"]
    print(f"proxy mode: {mode}   rules: {', '.join(health['rules'])}\n")

    steps = [
        ("cart-recovery", 10, "abandoned cart, 10% off"),
        ("subscription-recovery", 8, "mandate failed, 8% retry offer"),
    ]

    results = []
    for agent, pct, desc in steps:
        ok, text = await call(
            agent, "create_payment_link", link_args(pct, f"Commons Day 3 - {desc}")
        )
        if ok:
            obj = json.loads(text)
            print(f"  {agent:<24} {pct:>2}% -> ALLOWED  {obj.get('id')}")
        else:
            print(f"  {agent:<24} {pct:>2}% -> REFUSED   {text[:150]}")
        results.append((agent, pct, ok, text))

    print()
    allowed = [r for r in results if r[2]]
    delivered = sum(r[1] for r in allowed)
    print(f"discount actually delivered to the customer: {delivered}%  (cap is 15%)")

    if mode == "OBSERVE":
        assert all(r[2] for r in results), "OBSERVE must let everything through"
        print("OBSERVE: both allowed. The violation was recorded, not prevented.")
        print("         This is run 1 — the damage is real and visible in the ledger.")
    else:
        assert results[0][2], "the first, compliant call should have gone through"
        assert not results[1][2], "ENFORCE should have refused the second call"
        assert "Commons" in results[1][3]
        assert delivered <= 15
        print("ENFORCE: the second grant was refused by Commons before reaching Razorpay.")
        print("         Neither agent did anything wrong. The sum was the problem.")

    print(f"\nDAY 3 DoD PASSED ({mode})")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
