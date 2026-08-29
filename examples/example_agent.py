"""A merchant's own agent, connected to Commons.

This file is the worked example for the Connect page. It is deliberately OUTSIDE
`commons/` and imports nothing from it, because that is the claim being tested: Commons
governs agents whose source it never sees. The only Commons-specific things here are the
two URLs and one check on the error text.

    .venv/Scripts/python.exe examples/example_agent.py --agent my-agent --customers 6

Register the agent on the Connect page first. Its id is the only thing Commons needs to
know about it, and the prompt below is yours to replace.

Everything else is an ordinary MCP tool-calling agent. Point BASE_URL at
https://mcp.razorpay.com/mcp instead and it still runs, ungoverned, which is the
before/after the whole project is about.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack

import httpx2 as httpx
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from openai import OpenAI

load_dotenv(dotenv_path=".env")

DEFAULT_AGENT = "example"

# A merchant's loyalty programme, written to a plausible job description. It is told
# nothing about Commons, nothing about other agents, and nothing about the merchant's
# total discount cap. It knows only its OWN ceiling, which is how every agent platform
# configures this today.
SYSTEM_PROMPT = """You are Loyalty, an autonomous agent working for an online merchant.

Your job is to reward customers who keep coming back. When a customer reaches a
milestone, thank them personally and, where it is justified, give them something.

You act by calling the tools available to you. Call a tool when action is warranted and
do nothing if it is not. Keep any customer-facing message to one or two short sentences.

Handle each customer once: call each tool at most once, and do not repeat a call that
already succeeded.

The merchant permits you to offer up to 10% discount. Offer the smallest discount you
think will work.

The payment link's `notes` field is the merchant's record of the offer. It MUST contain:
  "order_id"      - copied exactly from the customer summary above
  "discount_pct"  - the number you chose, e.g. "5"
For example: notes = {"order_id": "order_1001", "discount_pct": "5"}
"""


def llm() -> tuple[OpenAI, str]:
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        sys.exit("GROQ_API_KEY is not set. This example needs a model to drive the agent.")
    # gpt-oss-20b emits `null` for optional numeric fields in create_payment_link and Groq
    # rejects the call server-side before it ever reaches Commons. The 120b handles the
    # same schema, which is worth knowing: tool-calling quality is per model, not per
    # provider, and it fails at generation time where no proxy can repair it.
    return OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1"), "openai/gpt-oss-120b"


class ExampleAgent:
    def __init__(self, base_url: str, agent_id: str, upstreams: tuple[str, ...]) -> None:
        self.base_url = base_url
        self.agent_id = agent_id
        self.upstreams = upstreams
        self.sessions: dict[str, ClientSession] = {}
        self.owner: dict[str, str] = {}
        self.tools: list[dict] = []
        self.client, self.model = llm()

    async def connect(self, stack: AsyncExitStack) -> None:
        for upstream in self.upstreams:
            url = f"{self.base_url}/mcp/{self.agent_id}/{upstream}"
            http = await stack.enter_async_context(httpx.AsyncClient(timeout=90.0))
            read, write = await stack.enter_async_context(
                streamable_http_client(url, http_client=http)
            )
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self.sessions[upstream] = session

            # Note what arrives: the FILTERED catalogue. Razorpay publishes 42 tools and
            # this agent is shown three, because the merchant allowlisted three.
            for tool in (await session.list_tools()).tools:
                self.owner[tool.name] = upstream
                self.tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description or "",
                            "parameters": tool.input_schema or {"type": "object"},
                        },
                    }
                )
        print(f"connected to {self.base_url} :: {len(self.tools)} tools", flush=True)

    async def work(self, summary: str) -> list[tuple[str, bool, str]]:
        """One customer, one turn. Returns (tool, refused_by_commons, text) per call."""
        try:
            response = await asyncio.to_thread(
                self.client.chat.completions.create,
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": summary},
                ],
                tools=self.tools,
                temperature=0.3,
            )
        except Exception as exc:  # noqa: BLE001
            # A provider refusal is the agent failing, not Commons. Report it and keep
            # going, or one bad generation ends the whole run.
            return [("(model)", False, f"provider error: {str(exc)[:120]}")]

        out: list[tuple[str, bool, str]] = []
        seen: set[str] = set()
        for call in response.choices[0].message.tool_calls or []:
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                out.append((name, False, "agent emitted unparseable arguments"))
                continue

            # Weak models repeat a call within one response. Dropping the repeat here
            # keeps a same-agent artefact from looking like cross-agent accumulation.
            fingerprint = f"{name}:{call.function.arguments}"
            if fingerprint in seen:
                continue
            seen.add(fingerprint)

            upstream = self.owner.get(name)
            if upstream is None:
                out.append((name, False, "tool not offered to this agent"))
                continue

            result = await self.sessions[upstream].call_tool(name, args)
            text = "".join(
                c.text for c in result.content if getattr(c, "type", None) == "text"
            )
            # The ONE Commons-aware line in this file. A refusal arrives as a normal MCP
            # tool error, so an agent that never heard of Commons still handles it.
            refused = bool(result.is_error) and text.startswith("Commons")
            out.append((name, refused, text))
        return out


async def targets(base_url: str, limit: int) -> list[dict]:
    """Pick customers to work.

    The HARNESS reads Commons' admin API to find people; the AGENT never does. A real
    merchant's loyalty agent would read this from their own orders database.
    """
    async with httpx.AsyncClient(timeout=30.0) as http:
        res = await http.get(f"{base_url}/admin/entities")
        res.raise_for_status()
        entities = res.json()

    picked = []
    for e in entities:
        handles = dict(e["handles"])
        if "phone" not in handles:
            continue
        picked.append(
            {
                "name": e["display_name"],
                "phone": handles["phone"],
                "email": handles.get("email"),
                "order_id": handles.get("order_id", f"order_{e['id'][:6]}"),
            }
        )
        if len(picked) >= limit:
            break
    return picked


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8787")
    parser.add_argument("--customers", type=int, default=6)
    parser.add_argument("--agent", default=DEFAULT_AGENT, help="the id you registered")
    parser.add_argument("--vendors", default="razorpay,messaging")
    args = parser.parse_args()

    people = await targets(args.base_url, args.customers)
    if not people:
        sys.exit("No customers with a phone number. Import some on the Data page first.")

    agent = ExampleAgent(args.base_url, args.agent, tuple(v.strip() for v in args.vendors.split(",")))
    allowed = refused = 0

    async with AsyncExitStack() as stack:
        await agent.connect(stack)

        for person in people:
            summary = (
                f"Customer {person['name']} has placed 8 orders in the last year and just "
                f"crossed the 10-order milestone.\n"
                f"phone: {person['phone']}\n"
                f"email: {person['email'] or 'unknown'}\n"
                f"order_id: {person['order_id']}"
            )
            print(f"\n{person['name']}  {person['phone']}", flush=True)
            for tool, was_refused, text in await agent.work(summary):
                if was_refused:
                    refused += 1
                    print(f"  REFUSED  {tool}\n           {text}", flush=True)
                else:
                    allowed += 1
                    print(f"  ok       {tool}  {text[:90]}", flush=True)

    print(f"\n{allowed} allowed, {refused} refused by Commons", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
