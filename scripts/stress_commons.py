"""Stress and edge-case harness for the Commons gateway.

    .venv/Scripts/python.exe scripts/stress_commons.py

Runs against a SEPARATE proxy on its own port and its own database, with in-memory
upstreams, so it never touches Razorpay's test account (which caps payment links at 30)
and never disturbs the merchant's own ledger. It registers its own agents through the
same admin API a merchant uses, so it exercises the real onboarding path.

Deliberately no LLM. A stress test should measure Commons, not model variance, and a
deterministic driver can hammer far harder than a free-tier quota allows.

What it probes, in order:

  1. LOAD          many agents x many customers, checking totals against the ledger
  2. CONCURRENCY   simultaneous calls on ONE customer, which is where a read-then-write
                   decision path can let two calls both pass a cap neither should
  3. EDGE CASES    out-of-scope tools, unknown agents, unresolvable entities, junk args
  4. ENFORCE       the same traffic with enforcement on, confirming calls are stopped
  5. LATENCY       what Commons adds per call
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from contextlib import AsyncExitStack

import httpx2 as httpx
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from commons.config import UpstreamConfig
from commons.proxy.app import create_app
from mcp_servers.fake_razorpay.server import build_fake_razorpay
from mcp_servers.messaging.server import build_messaging_server

PORT = 8799
BASE = f"http://127.0.0.1:{PORT}"
DB = "stress.db"
AGENTS_FILE = "stress-agents.yaml"

# The harness registers its own agents through the same API a merchant uses, so it is
# testing the real onboarding path rather than a fixture.
TEST_AGENTS = {
    "load-a": {"razorpay": ["create_payment_link", "fetch_order"], "messaging": ["send_whatsapp"]},
    "load-b": {"razorpay": ["create_payment_link", "fetch_order"], "messaging": ["send_whatsapp"]},
    "load-c": {"razorpay": ["create_payment_link", "fetch_order"], "messaging": ["send_whatsapp"]},
    "reader": {"razorpay": ["fetch_order"], "messaging": ["send_whatsapp"]},
}

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((PASS if ok else FAIL, name, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}", flush=True)


# ----------------------------------------------------------------- plumbing


def stress_upstreams() -> dict[str, UpstreamConfig]:
    return {
        "razorpay": UpstreamConfig(
            name="razorpay", kind="memory", server_factory=build_fake_razorpay
        ),
        "messaging": UpstreamConfig(
            name="messaging", kind="memory", server_factory=build_messaging_server
        ),
    }


class Client:
    """One agent's MCP session pair, opened against the stress proxy."""

    def __init__(self, agent: str) -> None:
        self.agent = agent
        self.sessions: dict[str, ClientSession] = {}

    async def open(self, stack: AsyncExitStack, upstreams=("razorpay", "messaging")) -> None:
        for up in upstreams:
            http = await stack.enter_async_context(httpx.AsyncClient(timeout=60.0))
            read, write = await stack.enter_async_context(
                streamable_http_client(f"{BASE}/mcp/{self.agent}/{up}", http_client=http)
            )
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self.sessions[up] = session

    async def call(self, upstream: str, tool: str, args: dict) -> tuple[bool, str]:
        res = await self.sessions[upstream].call_tool(tool, args)
        text = "".join(c.text for c in res.content if getattr(c, "type", None) == "text")
        return bool(res.is_error), text


async def api(method: str, path: str, body: dict | None = None):
    async with httpx.AsyncClient(timeout=30.0) as http:
        res = await http.request(method, f"{BASE}{path}", json=body)
        res.raise_for_status()
        return res.json()


def link_args(phone: str, pct: int, order: str) -> dict:
    return {
        "amount": 249900,
        "currency": "INR",
        "description": "offer",
        "customer_contact": phone,
        "customer_name": "Stress Customer",
        "notes": {"order_id": order, "discount_pct": str(pct)},
    }


# ----------------------------------------------------------------- probes


async def probe_load(stack: AsyncExitStack, agents: list[str], customers: int) -> None:
    print("\n1. LOAD", flush=True)
    await api("POST", "/admin/run", {"notes": "stress load"})

    clients = []
    for agent in agents:
        c = Client(agent)
        await c.open(stack)
        clients.append(c)

    phones = [f"+9198000{i:05d}" for i in range(customers)]
    started = time.perf_counter()

    sent = 0
    for i, phone in enumerate(phones):
        for c in clients:
            await c.call("messaging", "send_whatsapp", {"to": phone, "body": "hi"})
            sent += 1
        # One discount per customer from the first agent, so totals are predictable.
        await clients[0].call("razorpay", "create_payment_link", link_args(phone, 5, f"order_{i}"))
        sent += 1

    elapsed = time.perf_counter() - started
    run = await api("GET", "/api/run")
    recorded = run["stats"]["calls"]
    check("every call reached the ledger", recorded == sent, f"{recorded}/{sent}")
    check("throughput", elapsed > 0, f"{sent} calls in {elapsed:.1f}s ({sent / elapsed:.1f}/s)")

    # Each customer got one message per agent. With max=1 per 24h, agents 2..n breach.
    expected_breaches = customers * (len(agents) - 1)
    freq = sum(
        1 for c in run["calls"] for v in c["violations"] if v["rule_id"] == "msg_frequency"
    )
    check(
        "msg_frequency fired across agents, not within one",
        freq == expected_breaches,
        f"{freq} breaches, expected {expected_breaches}",
    )


async def probe_concurrency(stack: AsyncExitStack) -> None:
    """Every agent that can grant a discount does so to ONE customer at the same instant.

    The decision path reads the ledger, decides, then writes, and nothing holds a lock
    across those three steps. If concurrent calls each read the same prior total, they
    can all conclude they fit under a cap that only one of them does.

    The arithmetic is chosen so the two outcomes cannot be confused. N agents grant PCT
    each on DIFFERENT resources, with N*PCT above the cap and (N-1)*PCT below it:
      serialised -> the last one sees the others and breaches
      raced      -> all of them see zero and none breaches
    """
    print("\n2. CONCURRENCY", flush=True)
    await api("POST", "/admin/run", {"notes": "stress concurrency"})

    # Taken from the registry rather than hardcoded, so this cannot silently degrade into
    # testing nothing when an allowlist changes. It did exactly that on the first run:
    # rto-shield has no create_payment_link, so the load was a third short of the cap.
    granting = [a for a, tools in TEST_AGENTS.items() if "create_payment_link" in tools["razorpay"]]
    cap, pct = 15, 6
    assert len(granting) * pct > cap >= (len(granting) - 1) * pct, (
        f"{len(granting)} agents x {pct}% does not straddle a cap of {cap}"
    )

    clients = []
    for agent in granting:
        c = Client(agent)
        await c.open(stack, upstreams=("razorpay",))
        clients.append(c)

    phone = "+919899000001"
    await asyncio.gather(
        *[
            c.call("razorpay", "create_payment_link", link_args(phone, pct, f"conc_{i}"))
            for i, c in enumerate(clients)
        ]
    )

    run = await api("GET", "/api/run")
    granted = sum(
        c["magnitude"] or 0
        for c in run["calls"]
        if c["action_class"] == "discount_grant" and c["forwarded"]
    )
    breaches = sum(
        1 for c in run["calls"] for v in c["violations"] if v["rule_id"] == "discount_cap"
    )
    check(
        "concurrent grants over the cap are caught",
        breaches >= 1,
        f"{len(granting)} agents x {pct}% = {granted:g}% against a {cap}% cap, "
        f"{breaches} breach(es) flagged",
    )


async def probe_edges(stack: AsyncExitStack) -> None:
    print("\n3. EDGE CASES", flush=True)
    await api("POST", "/admin/run", {"notes": "stress edges"})

    c = Client("load-a")  # needs an agent that can actually grant
    await c.open(stack)

    # A tool the merchant did not allowlist for this agent.
    err, text = await c.call("razorpay", "fetch_payment", {"payment_id": "pay_1"})
    check("out-of-scope tool refused", err and "approved scope" in text, text[:70])

    # A tool nobody has ever heard of.
    err, text = await c.call("razorpay", "definitely_not_a_tool", {})
    check("unknown tool refused", err, text[:70])

    # Required argument missing: the vendor should reject, and Commons should record it
    # without counting it against the customer.
    err, _ = await c.call("razorpay", "create_payment_link", {"currency": "INR"})
    check("vendor rejection surfaces as an error", err)

    # A discount naming no customer at all.
    err, _ = await c.call(
        "razorpay",
        "create_payment_link",
        {"amount": 100, "currency": "INR", "notes": {"discount_pct": "5"}},
    )
    check("unresolvable entity does not crash the gateway", not err)

    # Junk in a field the manifest reads for magnitude.
    err, _ = await c.call(
        "razorpay",
        "create_payment_link",
        link_args("+919899000002", 0, "junk") | {"notes": {"discount_pct": "not-a-number"}},
    )
    check("non-numeric magnitude does not crash the gateway", not err)

    # An agent id that was never registered.
    async with httpx.AsyncClient(timeout=15.0) as http:
        res = await http.post(f"{BASE}/mcp/ghost-agent/razorpay", json={})
        check("unregistered agent id is not routed", res.status_code in (404, 405), f"HTTP {res.status_code}")

    run = await api("GET", "/api/run")
    rejected = [c for c in run["calls"] if c.get("is_error")]
    consumed = sum(
        c["magnitude"] or 0
        for c in rejected
        if c["action_class"] == "discount_grant"
    )
    check(
        "vendor-rejected grants recorded but not counted",
        len(rejected) >= 1,
        f"{len(rejected)} rejected, {consumed:g}% would have been counted before the fix",
    )


async def probe_enforce(stack: AsyncExitStack) -> None:
    print("\n4. ENFORCE", flush=True)
    await api("PUT", "/api/policy", {"mode": "ENFORCE"})
    await api("POST", "/admin/run", {"notes": "stress enforce"})

    c = Client("reader")
    await c.open(stack, upstreams=("messaging",))

    phone = "+919899000010"
    first_err, _ = await c.call("messaging", "send_whatsapp", {"to": phone, "body": "one"})
    second_err, second_text = await c.call("messaging", "send_whatsapp", {"to": phone, "body": "two"})

    check("first message allowed", not first_err)
    check("second message stopped", second_err and second_text.startswith("Commons"), second_text[:70])

    run = await api("GET", "/api/run")
    forwarded = [c for c in run["calls"] if c["forwarded"]]
    check("stopped call never reached the vendor", len(forwarded) == 1, f"{len(forwarded)} forwarded")

    await api("PUT", "/api/policy", {"mode": "OBSERVE"})


async def probe_latency(stack: AsyncExitStack) -> None:
    print("\n5. LATENCY", flush=True)
    await api("POST", "/admin/run", {"notes": "stress latency"})

    c = Client("reader")
    await c.open(stack, upstreams=("messaging",))

    samples = []
    for i in range(40):
        started = time.perf_counter()
        await c.call("messaging", "send_whatsapp", {"to": f"+9198991{i:05d}", "body": "x"})
        samples.append((time.perf_counter() - started) * 1000)

    samples.sort()
    p50, p95 = statistics.median(samples), samples[int(len(samples) * 0.95)]
    check("round trip through Commons", p95 < 250, f"p50 {p50:.0f}ms  p95 {p95:.0f}ms")


# ----------------------------------------------------------------- main


async def run_all(agents: list[str], customers: int) -> int:
    async with AsyncExitStack() as stack:
        await probe_load(stack, agents, customers)
        await probe_concurrency(stack)
        await probe_edges(stack)
        await probe_enforce(stack)
        await probe_latency(stack)

    failures = [r for r in results if r[0] == FAIL]
    print(f"\n{len(results) - len(failures)}/{len(results)} passed", flush=True)
    for _, name, detail in failures:
        print(f"  FAILED: {name}  {detail}", flush=True)
    return 1 if failures else 0


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--customers", type=int, default=25)
    args = parser.parse_args()

    agents = list(TEST_AGENTS)

    app = create_app(
        upstream_configs=stress_upstreams(), db_path=DB, mode="OBSERVE", agents_path=AGENTS_FILE
    )
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="error")
    server = uvicorn.Server(config)
    serving = asyncio.create_task(server.serve())

    for _ in range(60):
        await asyncio.sleep(0.25)
        if server.started:
            break
    else:
        print("stress proxy did not start", file=sys.stderr)
        return 1

    print(f"stress proxy on {BASE}, db={DB}, in-memory upstreams", flush=True)
    for agent_id, tools in TEST_AGENTS.items():
        await api("POST", "/admin/agents", {"id": agent_id, "tools": tools})
    print(f"registered {len(TEST_AGENTS)} agents through the admin API", flush=True)

    try:
        return await run_all(agents, args.customers)
    finally:
        server.should_exit = True
        await serving


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
