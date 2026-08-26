"""Drive a full simulated month through Commons.

    commons run --seed 4471 --mode OBSERVE

The loop is deliberately dumb: an event happens, the agent whose job it is wakes up and
decides for itself, its tool calls travel through Commons to real vendors, and the
customer reacts. Nothing coordinates the agents, because in the world this models
nothing does.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from contextlib import AsyncExitStack
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

import httpx2 as httpx

from commons.agents.base import AgentOutcome, AgentRuntime
from commons.agents.definitions import AGENT_DEFINITIONS, definition_for_event
from commons.world.personas import (
    PersonaContext,
    PersonaEngine,
    Reaction,
    apply_reaction,
    archetype_for,
)
from commons.world.events import EventType
from commons.world.seed import seed_identities
from commons.world.world import build_world

logger = logging.getLogger(__name__)

BASE_URL = "http://127.0.0.1:8787"

# Tools that put a message in front of a human. A persona reacts to these.
OUTBOUND_TOOLS = {"send_whatsapp", "send_email", "payment_link_notify"}


@dataclass
class RunReport:
    seed: int
    mode: str
    days: int
    customers: int
    events: int
    world_summary: dict = field(default_factory=dict)
    outcomes: list[dict] = field(default_factory=list)
    reactions: list[dict] = field(default_factory=list)
    malformed_tool_calls: int = 0
    duplicate_tool_calls: int = 0
    agent_errors: int = 0
    llm: dict = field(default_factory=dict)
    ledger: dict = field(default_factory=dict)


def compact_context(customer, event) -> str:
    """What this agent legitimately knows.

    Two constraints, both load-bearing:
      - it contains NOTHING about other agents or their actions, because no real agent
        would have that;
      - it is deliberately small (~50 tokens, not ~900) so the free tiers survive a full
        run (handoff §16.3).
    """
    lines = [
        f"Customer {customer.id} ({customer.name})",
        f"phone: {customer.phone}",
        f"email: {customer.email}",
        f"Event: {event.type}",
    ]
    payload = event.payload
    if "cart_value_paise" in payload:
        lines.append(f"Cart value: Rs {payload['cart_value_paise'] / 100:,.0f}")
    if "order_id" in payload:
        lines.append(f"Order: {payload['order_id']}")
    if "amount_paise" in payload:
        lines.append(f"Disputed amount: Rs {payload['amount_paise'] / 100:,.0f}")
    if "risk_score" in payload:
        lines.append(f"Return risk score: {payload['risk_score']}")
    if "reason" in payload:
        lines.append(f"Reason: {payload['reason']}")
    return "\n".join(lines)


class Runner:
    def __init__(
        self,
        seed: int = 4471,
        mode: str = "OBSERVE",
        days: int = 30,
        customers: int = 20,
        base_url: str = BASE_URL,
        limit: int | None = None,
    ) -> None:
        self.seed = seed
        self.mode = mode
        self.days = days
        self.base_url = base_url
        self.limit = limit
        self.world = build_world(seed=seed, n_customers=customers, days=days)
        self.personas = PersonaEngine()
        self.contacts: dict[str, list[datetime]] = {}
        self.run_id: str | None = None
        self.report = RunReport(
            seed=seed, mode=mode, days=days, customers=customers, events=0
        )

    # ---------------------------------------------------------------- gateway admin

    async def _post(self, path: str, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=60.0) as hc:
            response = await hc.post(f"{self.base_url}{path}", json=payload)
            response.raise_for_status()
            return response.json()

    async def set_clock(self, when: datetime) -> None:
        await self._post("/admin/clock", {"now": when.isoformat()})

    async def set_state(self, customer, key: str, value) -> None:
        await self._post("/admin/state", {"ref": customer.id, "key": key, "value": value})

    async def apply_event_state(self, customer, event) -> None:
        """Let the world's own events move entity state, before any agent reacts.

        A dispute being filed IS the customer having an open dispute. Until this existed,
        only a persona escalation ever set the flag, so a dispute the world generated was
        invisible to the rules and `no_promo_during_dispute` could never fire — the
        customer was in dispute and Commons had no idea.
        """
        if event.type == EventType.DISPUTE_FILED and customer.dispute_status != "open":
            customer.dispute_status = "open"
            await self.set_state(customer, "dispute_status", "open")
        elif event.type == EventType.DISPUTE_RESOLVED and customer.dispute_status == "open":
            customer.dispute_status = "closed"
            await self.set_state(customer, "dispute_status", "closed")

    # ---------------------------------------------------------------- personas

    def contacts_in_last_day(self, customer_id: str, now: datetime) -> int:
        window = now - timedelta(hours=24)
        return sum(1 for t in self.contacts.get(customer_id, []) if t >= window)

    async def react_to_contacts(self, customer, outcome: AgentOutcome, now: datetime) -> None:
        """A customer reacts to each message that actually reached them."""
        for attempt in outcome.attempts:
            if attempt.tool not in OUTBOUND_TOOLS or not attempt.ok:
                continue

            self.contacts.setdefault(customer.id, []).append(now)
            discount = 0.0
            notes = attempt.arguments.get("notes") or {}
            if isinstance(notes, dict):
                try:
                    discount = float(str(notes.get("discount_pct", 0)).rstrip("%") or 0)
                except ValueError:
                    discount = 0.0

            result = self.personas.decide(
                PersonaContext(
                    archetype=archetype_for(customer.id),
                    contacts_24h=self.contacts_in_last_day(customer.id, now),
                    contacts_total=len(self.contacts.get(customer.id, [])),
                    discount_pct=discount,
                    dispute_open=customer.dispute_status == "open",
                    irritation=customer.irritation,
                    already_opted_out=customer.opted_out,
                )
            )
            was_open = customer.dispute_status == "open"
            effects = apply_reaction(customer, result.reaction)

            self.report.reactions.append(
                {
                    "at": now.isoformat(),
                    "customer_id": customer.id,
                    "by_agent": outcome.agent_id,
                    "tool": attempt.tool,
                    "reaction": str(result.reaction),
                    "source": result.source,
                    "text": result.text,
                    "effects": effects,
                }
            )

            # A dispute opened by irritation is real state the RULES must see —
            # every later promotional contact to this person is now a violation.
            if customer.dispute_status == "open" and not was_open:
                await self.set_state(customer, "dispute_status", "open")
                logger.warning(
                    "%s opened a dispute after being contacted by %s",
                    customer.id,
                    outcome.agent_id,
                )
            if result.reaction == Reaction.OPT_OUT:
                await self.set_state(customer, "opted_out", "true")

    # ---------------------------------------------------------------- the run

    async def run(self) -> RunReport:
        events = self.world.generate()
        if self.limit:
            events = events[: self.limit]
        self.report.events = len(events)
        self.report.world_summary = self.world.summary()

        started = await self._post("/admin/run", {"seed": self.seed, "notes": f"seed {self.seed}"})
        self.run_id = started["run_id"]
        logger.info("ledger run %s", self.run_id)

        seed_identities(self.world, self.base_url)
        logger.info("declared %d customers", len(self.world.customers))

        async with AsyncExitStack() as stack:
            runtimes: dict[str, AgentRuntime] = {}
            for definition in AGENT_DEFINITIONS.values():
                runtime = AgentRuntime(definition, base_url=self.base_url)
                await runtime.connect(stack)
                runtimes[definition.id] = runtime

            for index, event in enumerate(events, 1):
                definition = definition_for_event(str(event.type))
                if definition is None:
                    continue
                customer = self.world.customers[event.customer_id]

                await self.set_clock(event.at)
                await self.apply_event_state(customer, event)
                outcome = await runtimes[definition.id].handle(
                    event, compact_context(customer, event)
                )

                self.report.outcomes.append(
                    {
                        "at": event.at.isoformat(),
                        "event": str(event.type),
                        "agent": outcome.agent_id,
                        "customer_id": outcome.customer_id,
                        "attempts": [asdict(a) for a in outcome.attempts],
                        "malformed": outcome.malformed,
                        "duplicates": outcome.duplicates,
                        "error": outcome.error,
                    }
                )
                self.report.malformed_tool_calls += outcome.malformed
                self.report.duplicate_tool_calls += outcome.duplicates
                self.report.agent_errors += 1 if outcome.error else 0

                await self.react_to_contacts(customer, outcome, event.at)

                logger.info(
                    "[%d/%d] %s %s %s -> %d calls, %d refused",
                    index,
                    len(events),
                    event.at.strftime("%d %b %H:%M"),
                    outcome.agent_id,
                    event.customer_id,
                    len(outcome.attempts),
                    outcome.refusals,
                )

            # Read cache stats from a runtime that actually ran, while it is still alive —
            # a freshly built one reports zero hits because its counters start empty.
            any_runtime = next(iter(runtimes.values()))
            self.report.llm = any_runtime.llm.cache.stats()

        # Reset the gateway clock so it goes back to wall time.
        await self._post("/admin/clock", {"now": None})
        return self.report


def summarise_ledger(db_path: str, run_id: str | None = None) -> dict:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    if run_id is None:
        row = conn.execute("SELECT id FROM run ORDER BY started_at DESC LIMIT 1").fetchone()
        run_id = row["id"] if row else None

    calls = conn.execute(
        "SELECT COUNT(*) n FROM call WHERE run_id = ?", (run_id,)
    ).fetchone()["n"]
    forwarded = conn.execute(
        "SELECT COUNT(*) n FROM call WHERE run_id = ? AND forwarded = 1", (run_id,)
    ).fetchone()["n"]
    by_decision = {
        r["decision"]: r["n"]
        for r in conn.execute(
            "SELECT decision, COUNT(*) n FROM call WHERE run_id = ? GROUP BY decision",
            (run_id,),
        )
    }
    by_rule = {
        r["rule_id"]: r["n"]
        for r in conn.execute(
            """SELECT rf.rule_id, COUNT(*) n FROM rule_fired rf
               JOIN call c ON c.id = rf.call_id
               WHERE c.run_id = ? AND rf.verdict != 'ALLOW'
               GROUP BY rf.rule_id""",
            (run_id,),
        )
    }
    # A contradiction resolves as ALLOW — the restriction wins — so it never appears
    # under "violations", yet one agent restricting a customer another is incentivising
    # is exactly the conflict this project is about. Count it explicitly.
    contradictions = conn.execute(
        """SELECT COUNT(*) n FROM rule_fired rf
           JOIN call c ON c.id = rf.call_id
           WHERE c.run_id = ? AND rf.rule_id = 'restriction_beats_incentive'""",
        (run_id,),
    ).fetchone()["n"]

    affected = conn.execute(
        """SELECT COUNT(DISTINCT c.entity_id) n FROM rule_fired rf
           JOIN call c ON c.id = rf.call_id
           WHERE c.run_id = ? AND rf.verdict != 'ALLOW'""",
        (run_id,),
    ).fetchone()["n"]
    discount = conn.execute(
        """SELECT COALESCE(SUM(magnitude), 0) s FROM call
           WHERE run_id = ? AND forwarded = 1 AND action_class = 'discount_grant'""",
        (run_id,),
    ).fetchone()["s"]

    # The convergence itself, which is the finding even when no rule breaks. A customer
    # being worked by three agents that cannot see each other is the exposure; whether a
    # threshold happened to be crossed is downstream of it.
    multi_agent = conn.execute(
        """SELECT COUNT(*) n FROM (
               SELECT entity_id FROM call WHERE run_id = ? AND forwarded = 1
               GROUP BY entity_id HAVING COUNT(DISTINCT agent_id) > 1)""",
        (run_id,),
    ).fetchone()["n"]

    per_customer = conn.execute(
        """SELECT entity_id, COUNT(DISTINCT agent_id) agents, SUM(magnitude) total
           FROM call
           WHERE run_id = ? AND forwarded = 1 AND action_class = 'discount_grant'
           GROUP BY entity_id""",
        (run_id,),
    ).fetchall()
    at_cap = sum(1 for r in per_customer if (r["total"] or 0) >= 15)
    cross_agent_discount = sum(1 for r in per_customer if r["agents"] > 1)
    conn.close()

    return {
        "run_id": run_id,
        "calls": calls,
        "forwarded": forwarded,
        "by_decision": by_decision,
        "violations_by_rule": by_rule,
        "customers_affected": affected,
        "total_discount_delivered_pct": discount,
        "customers_touched_by_multiple_agents": multi_agent,
        "customers_discounted_by_multiple_agents": cross_agent_discount,
        "customers_at_or_over_discount_cap": at_cap,
        "contradictions_detected": contradictions,
    }


async def execute(**kwargs) -> RunReport:
    runner = Runner(**{k: v for k, v in kwargs.items() if k != "db"})
    report = await runner.run()
    report.ledger = summarise_ledger(kwargs.get("db", "commons.db"), runner.run_id)
    return report


def run_sync(**kwargs) -> RunReport:
    return asyncio.run(execute(**kwargs))


def write_report(report: RunReport, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(asdict(report), fh, indent=2, default=str)
