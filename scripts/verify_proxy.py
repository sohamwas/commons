"""Day 1 definition-of-done.

An ordinary MCP client -> Commons -> Razorpay's remote MCP -> the real test API.
No Commons-specific client code: the agent thinks it is talking to Razorpay.

Asserts three things:
  1. Least privilege is enforced at the face: cart-recovery sees 3 of 42 tools.
  2. An out-of-scope call is refused by Commons, not by the upstream.
  3. An in-scope write is forwarded and creates a REAL payment link in test mode.

Requires the proxy to be running:  .venv/Scripts/python.exe scripts/run_proxy.py
"""

from __future__ import annotations

import asyncio
import json
import sys

import httpx2 as httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

BASE = "http://127.0.0.1:8787"
AGENT = "cart-recovery"
ENDPOINT = f"{BASE}/mcp/{AGENT}/razorpay"


async def main() -> int:
    async with httpx.AsyncClient(timeout=60.0) as hc:
        health = (await hc.get(f"{BASE}/health")).json()
        print(f"commons v{health['version']}  mode={health['mode']}  upstreams={health['upstreams']}")
        print(f"endpoints: {len(health['endpoints'])}")
        for e in health["endpoints"]:
            print(f"  {e}")

    print(f"\nconnecting as agent '{AGENT}' -> {ENDPOINT}")
    async with httpx.AsyncClient(timeout=60.0) as hc:
        async with streamable_http_client(ENDPOINT, http_client=hc) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                print(f"  server: {init.server_info.name} v{init.server_info.version}")

                # ---- 1. least privilege at the face ----
                tools = sorted(t.name for t in (await session.list_tools()).tools)
                print(f"\n  tools visible to {AGENT}: {len(tools)} (upstream exposes 42)")
                for t in tools:
                    print(f"    {t}")
                assert tools == [
                    "create_payment_link",
                    "fetch_all_payments",
                    "payment_link_notify",
                ], f"unexpected tool set: {tools}"

                # ---- 2. out-of-scope call refused BY COMMONS ----
                print("\n  calling out-of-scope tool 'update_order'...")
                res = await session.call_tool("update_order", {"order_id": "order_x"})
                text = "".join(c.text for c in res.content if getattr(c, "type", None) == "text")
                print(f"    is_error={res.is_error}  {text[:120]}")
                assert res.is_error and "not in cart-recovery" in text, "scope check failed"

                # ---- 3. in-scope write reaches the real test API ----
                print("\n  calling in-scope 'create_payment_link' (TEST, notify disabled)...")
                res = await session.call_tool(
                    "create_payment_link",
                    {
                        "amount": 420000,
                        "currency": "INR",
                        "description": "Commons Day 1 — proxied cart recovery",
                        "customer_name": "Priya S.",
                        "customer_email": "priya@example.com",
                        "customer_contact": "+919800000021",
                        "notify_sms": False,
                        "notify_email": False,
                        "notes": {"commons_run": "day1-verify", "discount_pct": "10"},
                    },
                )
                text = "".join(c.text for c in res.content if getattr(c, "type", None) == "text")
                assert not res.is_error, f"forwarded call failed: {text[:400]}"
                obj = json.loads(text)
                print(f"    SUCCESS  id={obj.get('id')}  amount={obj.get('amount')}")
                print(f"    short_url={obj.get('short_url')}")

    print("\nDAY 1 DoD PASSED — agent -> Commons -> Razorpay -> real test API")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
