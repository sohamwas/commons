"""Day 5 definition-of-done, live.

Three things:
  1. The merchant declares its customers, so phone/email/customer_id are one person.
  2. Two agents on two DIFFERENT CHANNELS (WhatsApp and email) now share a frequency
     cap, which they could not before.
  3. Personas react through a real LLM, and the third message changes the world.

    .venv/Scripts/python.exe mcp_servers/messaging/run.py --port 8788
    .venv/Scripts/python.exe scripts/run_proxy.py --mode ENFORCE --db day5.db
    .venv/Scripts/python.exe scripts/verify_day5.py
"""

from __future__ import annotations

import asyncio
import sqlite3
import sys

import httpx2 as httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from commons.world.personas import (
    ARCHETYPES,
    PersonaContext,
    PersonaEngine,
    apply_reaction,
    archetype_for,
)
from commons.world.seed import seed_identities
from commons.world.world import build_world

BASE = "http://127.0.0.1:8787"


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
    mode, db = health["mode"], "day5.db"
    print(f"proxy mode: {mode}\n")

    # ---------------------------------------------------------------- 1. declare
    print("1. DECLARING THE MERCHANT'S CUSTOMERS")
    world = build_world(seed=4471, n_customers=20)
    world.generate()
    mapping = seed_identities(world, BASE)
    priya = world.customers["cust_4471"]
    print(f"   declared {len(mapping)} customers")
    print(f"   {priya.id} ({priya.name}) -> {priya.entity_id}")
    print(f"      phone={priya.phone}  email={priya.email}")

    async with httpx.AsyncClient(timeout=30.0) as hc:
        entities = (await hc.get(f"{BASE}/admin/entities")).json()
    row = next(e for e in entities if e["id"] == priya.entity_id)
    print(f"   handles now on record: {row['handles']}")
    assert len(row["handles"]) == 3, "expected phone + email + customer_id"

    # ---------------------------------------------------------------- 2. channels
    print("\n2. TWO AGENTS, TWO CHANNELS, ONE CUSTOMER")
    ok1, _ = await call(
        "cart-recovery",
        "messaging",
        "send_whatsapp",
        {"to": priya.phone, "body": "Left something behind? 10% off.", "kind": "promotional"},
    )
    print(f"   cart-recovery     -> WhatsApp to {priya.phone:<16} {'SENT' if ok1 else 'REFUSED'}")

    ok2, text2 = await call(
        "dispute-responder",
        "messaging",
        "send_email",
        {"to": priya.email, "subject": "About your order", "body": "Following up.",
         "kind": "promotional"},
    )
    print(f"   dispute-responder -> email to    {priya.email:<16} {'SENT' if ok2 else 'REFUSED'}")
    if not ok2:
        print(f"      {text2[:170]}")

    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT agent_id, tool, entity_id, entity_ref, decision FROM call "
        "WHERE entity_id = ? ORDER BY id",
        (priya.entity_id,),
    ).fetchall()
    conn.close()

    print("\n   ledger:")
    for r in rows:
        print(f"     {r['agent_id']:<20} {r['tool']:<16} {r['entity_ref']:<22} {r['decision']}")

    assert len({r["entity_id"] for r in rows}) == 1, "channels did not unify"
    print("\n   Both channels resolved to ONE customer. Before the declaration these")
    print("   were two different people and no cap could span them.")
    if mode == "ENFORCE":
        assert not ok2, "the second contact, on another channel, should be stopped"

    # ---------------------------------------------------------------- 3. personas
    print("\n3. PERSONAS REACTING (real LLM, cached)")
    engine = PersonaEngine()
    print(f"   engine: {'OFFLINE fallback' if engine.offline else 'LLM ' + engine.client.model}")
    print("   three unsolicited messages in one day, per archetype:\n")

    def state_of(c) -> tuple:
        return (c.converted, c.opted_out, c.dispute_status, c.irritation)

    changed = 0
    walked_away = 0

    for archetype in sorted(ARCHETYPES):
        c = world.customers[f"cust_{4471 + list(sorted(ARCHETYPES)).index(archetype)}"]
        c.converted = c.opted_out = False
        c.irritation = 0
        c.dispute_status = "none"
        before = state_of(c)

        ladder = []
        for n in (1, 2, 3):
            result = engine.decide(
                PersonaContext(
                    archetype=archetype,
                    contacts_24h=n,
                    contacts_total=n,
                    discount_pct=5.0,
                    dispute_open=c.dispute_status == "open",
                    irritation=c.irritation,
                    already_opted_out=c.opted_out,
                )
            )
            apply_reaction(c, result.reaction)
            ladder.append(str(result.reaction))

        after = state_of(c)
        if after != before:
            changed += 1
        if c.opted_out or c.dispute_status == "open":
            walked_away += 1

        outcome = []
        if c.converted:
            outcome.append("converted")
        if c.opted_out:
            outcome.append("OPTED OUT")
        if c.dispute_status == "open":
            outcome.append("DISPUTE OPENED")
        if c.irritation:
            outcome.append(f"irritation={c.irritation}")

        print(
            f"   {archetype:<16} {' -> '.join(f'{r:<9}' for r in ladder)}"
            f"  {', '.join(outcome) or 'no change'}"
        )

    print(
        f"\n   {changed}/{len(ARCHETYPES)} archetypes changed state; "
        f"{walked_away} stopped being reachable or complained."
    )
    assert changed > 0, "contact fatigue produced no consequences at all"
    assert walked_away > 0, "nobody opted out or escalated after three messages in a day"
    print("   Contact fatigue has consequences: an opted-out or disputing customer")
    print("   changes what every later agent is allowed to do to them.")

    if not engine.offline:
        print(f"\n   LLM usage: {engine.client.cache.stats()}")

    print(f"\nDAY 5 DoD PASSED ({mode})")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
