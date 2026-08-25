"""Day 1 spike: can Commons drive Razorpay's REMOTE MCP server with test keys?

Answers the three questions that gate the whole architecture (IMPLEMENTATION_PLAN.md §5 Day 1):
  a. Does Basic auth against https://mcp.razorpay.com/mcp work with rzp_test_ keys?
  b. What tools does the REMOTE server actually expose? (docs admit restrictions, don't list them)
  c. Does create_payment_link succeed remotely, or do we need the local Go binary? (§7 R1)

Never prints key material.

  .venv/Scripts/python.exe scripts/spike_razorpay_mcp.py           # read-only
  .venv/Scripts/python.exe scripts/spike_razorpay_mcp.py --write   # also attempts a write
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
from pathlib import Path

import httpx2 as httpx
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

load_dotenv(dotenv_path=".env")

RAZORPAY_MCP_URL = "https://mcp.razorpay.com/mcp"
FIXTURE = Path("fixtures/razorpay_remote_tools.json")

# Write tools we care about for the demo. If create_payment_link is absent or fails,
# the fallbacks in §7 R1 kick in (create_order / create_refund, else local Go binary).
DEMO_CRITICAL = [
    "create_payment_link",
    "create_payment_link_upi",
    "create_order",
    "create_refund",
    "fetch_payment",
    "fetch_all_payments",
]


def auth_header() -> str:
    key_id = os.environ["RAZORPAY_KEY_ID"].strip()
    secret = os.environ["RAZORPAY_KEY_SECRET"].strip()
    if not key_id.startswith("rzp_test_"):
        print(f"  !! WARNING: key does not start with rzp_test_ — refusing to continue.")
        sys.exit(1)
    token = base64.b64encode(f"{key_id}:{secret}".encode()).decode()
    return f"Basic {token}"


async def main(do_write: bool) -> None:
    headers = {"Authorization": auth_header()}
    print(f"connecting: {RAZORPAY_MCP_URL}  (test key confirmed by prefix)")

    async with httpx.AsyncClient(headers=headers, timeout=60.0) as http_client:
        async with streamable_http_client(RAZORPAY_MCP_URL, http_client=http_client) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                print(f"  connected: {init.server_info.name} v{init.server_info.version}")
                print(f"  protocol:  {init.protocol_version}")

                # ---- (b) what does the REMOTE server actually expose? ----
                result = await session.list_tools()
                names = sorted(t.name for t in result.tools)
                print(f"\n  tools exposed remotely: {len(names)}")

                FIXTURE.parent.mkdir(parents=True, exist_ok=True)
                FIXTURE.write_text(
                    json.dumps(
                        {
                            "source": RAZORPAY_MCP_URL,
                            "server": f"{init.server_info.name} v{init.server_info.version}",
                            "tool_count": len(names),
                            "tools": names,
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                print(f"  fixture written: {FIXTURE}")

                print("\n  demo-critical tools:")
                for t in DEMO_CRITICAL:
                    print(f"    {'PRESENT' if t in names else 'ABSENT ':<8} {t}")

                writes = [n for n in names if n.split("_")[0] in ("create", "update", "capture", "close", "initiate", "submit", "resend", "revoke")]
                print(f"\n  write-capable tools present ({len(writes)}):")
                for n in writes:
                    print(f"    {n}")

                if not do_write:
                    print("\n  (read-only pass — rerun with --write to attempt create_payment_link)")
                    return

                # ---- (c) the fork in the road: does a write actually succeed? ----
                if "create_payment_link" not in names:
                    print("\n  create_payment_link ABSENT remotely -> §7 R1 fallback required")
                    return

                print("\n  attempting create_payment_link (TEST mode, notify DISABLED)...")
                # NOTE: create_payment_link's INPUT schema is flat (customer_contact,
                # notify_sms) even though the API response is nested (customer.contact).
                args = {
                    "amount": 420000,  # paise = ₹4,200 — Priya's cart from the demo script
                    "currency": "INR",
                    "description": "Commons spike — cart recovery",
                    "customer_name": "Priya S.",
                    "customer_email": "priya@example.com",
                    "customer_contact": "+919800000021",
                    # Nothing is sent to anyone. This is a connectivity test, not an outbound message.
                    "notify_sms": False,
                    "notify_email": False,
                    "notes": {"commons_spike": "true", "discount_pct": "10"},
                }
                try:
                    res = await session.call_tool("create_payment_link", args)
                    payload = "\n".join(
                        c.text for c in res.content if getattr(c, "type", None) == "text"
                    )
                    if res.is_error:
                        print(f"    TOOL ERROR -> §7 R1 fallback\n    {payload[:600]}")
                        return
                    print("    SUCCESS")
                    try:
                        obj = json.loads(payload)
                        for k in ("id", "short_url", "status", "amount"):
                            if k in obj:
                                print(f"      {k}: {obj[k]}")
                    except json.JSONDecodeError:
                        print(f"      {payload[:600]}")
                    print("\n  -> Check the Razorpay TEST dashboard. This link should be visible.")
                except Exception as exc:  # noqa: BLE001 - spike
                    print(f"    FAILED {type(exc).__name__}: {str(exc)[:600]}")
                    print("    -> §7 R1 fallback required")


if __name__ == "__main__":
    asyncio.run(main("--write" in sys.argv))
