"""CONTROL EXPERIMENT: do the agents behave differently without Commons in the path?

The worry this answers is the one that would sink the project if true — that the agents
somehow coordinate, or that Commons influences what they choose. Cart Recovery keeps
picking 5% while Subscription Recovery picks 10%, summing to exactly the 15% cap, and
that looks suspiciously tidy.

So: bypass Commons completely. Connect straight to Razorpay's remote MCP, give the agent
its real system prompt and a real event, and see what discount it picks. Three arms:

  A  direct, all 42 Razorpay tools     - no Commons, no scoping at all
  B  direct, the 3 tools it is scoped to - no Commons, merchant scoping only
  C  through Commons                   - the normal path

The LLM cache is BYPASSED here. A cached answer would make the comparison circular:
identical prompts would trivially return identical responses.

    .venv/Scripts/python.exe scripts/control_no_commons.py
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
from collections import Counter

import httpx2 as httpx
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from openai import OpenAI

from commons.agents.definitions import AGENT_DEFINITIONS
from commons.llm.client import load_config
from commons.proxy.registry import AGENTS

load_dotenv(dotenv_path=".env")

RAZORPAY_URL = "https://mcp.razorpay.com/mcp"
COMMONS_URL = "http://127.0.0.1:8787/mcp/cart-recovery/razorpay"
TRIALS = 3

AGENT_ID = "cart-recovery"
DEFINITION = AGENT_DEFINITIONS[AGENT_ID]

# The exact context the runner builds for this event.
CONTEXT = """Customer cust_4471 (Priya S.)
phone: +919800000021
email: priya0@example.com
Event: cart_abandoned
Cart value: Rs 4,200
Order: order_4471"""


def auth() -> dict:
    key, secret = os.environ["RAZORPAY_KEY_ID"], os.environ["RAZORPAY_KEY_SECRET"]
    token = base64.b64encode(f"{key}:{secret}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def llm() -> tuple[OpenAI, str]:
    cfg = load_config()
    spec = cfg["roles"][DEFINITION.role]
    provider = cfg["providers"][spec["provider"]]
    client = OpenAI(
        api_key=os.environ[provider["api_key_env"]],
        base_url=provider["base_url"],
        max_retries=6,
        timeout=90.0,
    )
    return client, spec["model"]


async def fetch_tools(url: str, headers: dict | None) -> list[dict]:
    async with httpx.AsyncClient(headers=headers or {}, timeout=90.0) as hc:
        async with streamable_http_client(url, http_client=hc) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return [
                    {
                        "type": "function",
                        "function": {
                            "name": t.name,
                            "description": t.description or "",
                            "parameters": t.input_schema or {"type": "object"},
                        },
                    }
                    for t in (await session.list_tools()).tools
                ]


def ask(client: OpenAI, model: str, tools: list[dict]) -> float | None:
    """One uncached invocation. Returns the discount the agent chose, if any."""
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": DEFINITION.system_prompt()},
            {"role": "user", "content": CONTEXT},
        ],
        tools=tools,
        tool_choice="auto",
        max_tokens=600,
        temperature=0.0,
    )
    for call in completion.choices[0].message.tool_calls or []:
        if call.function.name != "create_payment_link":
            continue
        try:
            args = json.loads(call.function.arguments or "{}")
        except json.JSONDecodeError:
            return None
        notes = args.get("notes") or {}
        if isinstance(notes, dict) and "discount_pct" in notes:
            try:
                return float(str(notes["discount_pct"]).rstrip("%"))
            except ValueError:
                return None
    return None


async def main() -> int:
    client, model = llm()
    print(f"agent: {AGENT_ID}   model: {model}")
    print(f"the merchant permits this agent up to {DEFINITION.max_discount_pct}%")
    print("the prompt never mentions Commons, other agents, or a 15% total cap.\n")

    all_tools = await fetch_tools(RAZORPAY_URL, auth())
    allowed = set(AGENTS[AGENT_ID].allowed("razorpay"))
    scoped = [t for t in all_tools if t["function"]["name"] in allowed]

    arms = [
        ("A  direct, all Razorpay tools", all_tools, f"{len(all_tools)} tools, no Commons"),
        ("B  direct, scoped tools", scoped, f"{len(scoped)} tools, no Commons"),
    ]
    try:
        commons_tools = await fetch_tools(COMMONS_URL, None)
        arms.append(
            ("C  through Commons", commons_tools, f"{len(commons_tools)} tools, via Commons")
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  (Commons arm skipped — proxy not running: {str(exc)[:60]})\n")

    results: dict[str, list[float | None]] = {}
    for label, tools, note in arms:
        picks = [ask(client, model, tools) for _ in range(TRIALS)]
        results[label] = picks
        shown = ", ".join("none" if p is None else f"{p:g}%" for p in picks)
        print(f"  {label:<32} {note:<26} -> {shown}")

    print()
    distinct = {
        label: Counter(p for p in picks if p is not None) for label, picks in results.items()
    }
    for label, counts in distinct.items():
        print(f"  {label:<32} {dict(counts)}")

    values = {
        tuple(sorted(c.keys())) for c in distinct.values() if c
    }
    print()
    if len(values) <= 1:
        print("  SAME CHOICE WITH AND WITHOUT COMMONS.")
        print("  The agent picks its discount from its own instructions and the customer's")
        print("  situation. Commons is not in that decision — in OBSERVE it forwards every")
        print("  call untouched, and the agent is never told it exists.")
    else:
        print("  DIFFERENT CHOICES BETWEEN ARMS — investigate before trusting any run.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
