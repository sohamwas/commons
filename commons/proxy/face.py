"""The MCP server face — what agents connect to.

One Server per (agent, upstream) pair. Agent identity therefore comes from the ROUTE
(`/mcp/{agent}/{upstream}`) rather than a header, which means it is closed over in the
handler and cannot be spoofed or lost. It also gives every agent its own onboarding
URL, which is exactly the shape of the Connect screen (handoff §13.2).

Every call flows through one path:

    scope check -> semantics -> entity resolution -> DECISION -> ledger -> forward

Day 3 fills in DECISION. Everything before it already works, which is why the rule
engine can be a pure function of (facts, ledger) rather than tangled into transport.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from mcp.server import Server, ServerRequestContext
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
)

from commons.proxy.registry import AgentSpec
from commons.proxy.upstream import Upstream
from commons.rules.engine import ENFORCE, RuleEngine
from commons.rules.primitives import ALLOW, BLOCK, EvalContext
from commons.semantics.manifest import CallFacts, Manifest, derive_facts

logger = logging.getLogger(__name__)

COMMONS_VERSION = "0.1.0"


def _denied(message: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=message)], is_error=True)


def _result_text(result: CallToolResult) -> str:
    return "".join(c.text for c in result.content if getattr(c, "type", None) == "text")


def build_face(
    agent: AgentSpec,
    upstream: Upstream,
    ledger,
    resolver,
    manifest: Manifest | None,
    engine: RuleEngine | None = None,
    mode: str = "OBSERVE",
    clock=None,
) -> Server:
    """An MCP server that presents `upstream` to `agent`, mediated by Commons.

    `clock` returns the current SIMULATED time; the world simulator injects its own on
    Day 4 so a 30-day month can run in a minute. Defaults to the wall clock.
    """

    now = clock or (lambda: datetime.now(timezone.utc))

    allowed = set(agent.allowed(upstream.name))
    # Entity lookups (order_id -> customer) are stable within a run; cache them so
    # resolution costs at most one extra upstream round trip per distinct resource.
    lookup_cache: dict[tuple, object] = {}

    async def on_list_tools(
        ctx: ServerRequestContext, params: PaginatedRequestParams | None
    ) -> ListToolsResult:
        tools = await upstream.list_tools()
        visible = [t for t in tools if t.name in allowed]
        logger.info(
            "list_tools agent=%s upstream=%s -> %d/%d tools",
            agent.id,
            upstream.name,
            len(visible),
            len(tools),
        )
        return ListToolsResult(tools=visible)

    async def on_call_tool(
        ctx: ServerRequestContext, params: CallToolRequestParams
    ) -> CallToolResult:
        args = dict(params.arguments or {})
        started = time.perf_counter()

        # Least privilege still applies, and applies first. Commons sits ALONGSIDE
        # per-agent scoping (handoff §6.1), it does not replace it.
        if params.name not in allowed:
            logger.warning(
                "OUT-OF-SCOPE agent=%s upstream=%s tool=%s", agent.id, upstream.name, params.name
            )
            return _denied(
                f"Commons: '{params.name}' is not in {agent.id}'s approved scope for "
                f"upstream '{upstream.name}'."
            )

        # ---- what does this call mean? (plan §3) ----
        sem = manifest.get(params.name) if manifest else None
        if sem is None:
            # A tool with no declared semantics cannot be governed. Log it loudly rather
            # than silently letting it past — a manifest gap is a real hole in coverage.
            logger.warning(
                "NO SEMANTICS agent=%s upstream=%s tool=%s — forwarding ungoverned",
                agent.id,
                upstream.name,
                params.name,
            )
            facts = CallFacts(action_class=None, governed=False)
        else:
            facts = await derive_facts(sem, args, resolver, upstream, lookup_cache)

        # ------------------------------------------------------------------
        # DECISION POINT. The engine evaluates against everything every OTHER agent
        # has already done to this entity. It is not told which mode it is running in
        # — that is the whole point of "one engine, two modes".
        # ------------------------------------------------------------------
        sim_now = now()
        if engine is not None:
            decision = engine.evaluate(
                facts,
                EvalContext(
                    ledger=ledger,
                    agent_id=agent.id,
                    now=sim_now,
                    run_id=ledger.run_id,
                ),
            )
        else:
            from commons.rules.engine import Decision

            decision = Decision(verdict=ALLOW)

        # In OBSERVE the violation is recorded and the call goes through anyway — that
        # is what makes run 1 show real damage. In ENFORCE the same decision is honoured.
        honour = mode == ENFORCE and decision.blocked

        call_id = ledger.record_call(
            agent_id=agent.id,
            upstream=upstream.name,
            tool=params.name,
            action_class=facts.action_class,
            entity_id=facts.entity_id,
            entity_ref=facts.entity_ref,
            magnitude=facts.magnitude,
            magnitude_unit=facts.magnitude_unit,
            resource=facts.resource,
            decision=decision.verdict,
            forwarded=0,
            args_json=args,
            sim_ts=sim_now.isoformat(timespec="milliseconds"),
        )
        for firing in decision.firings:
            ledger.record_rule_fired(
                call_id,
                rule_id=firing.rule_id,
                verdict=firing.verdict,
                reason=firing.reason,
                observed=firing.observed,
                limit_value=firing.limit_value,
                detail_json=firing.detail,
            )

        if decision.violations:
            logger.warning(
                "%s %s agent=%s tool=%s entity=%s :: %s",
                "STOPPED" if honour else "OBSERVED",
                decision.verdict,
                agent.id,
                params.name,
                facts.entity_id,
                decision.summary(),
            )

        if honour:
            ledger.update_call(call_id, latency_ms=int((time.perf_counter() - started) * 1000))
            reasons = "; ".join(f.reason for f in decision.violations)
            verb = "blocked" if decision.verdict == BLOCK else "deferred"
            return _denied(
                f"Commons {verb} this call under merchant policy across all agents: {reasons}"
            )

        result = await upstream.call_tool(params.name, args)
        text = _result_text(result)

        ledger.update_call(
            call_id,
            forwarded=1,
            result_json=text,
            is_error=1 if result.is_error else 0,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

        if not decision.violations:
            logger.info(
                "ALLOW agent=%s tool=%s action=%s entity=%s%s",
                agent.id,
                params.name,
                facts.action_class,
                facts.entity_id,
                f" magnitude={facts.magnitude}{facts.magnitude_unit or ''}"
                if facts.magnitude is not None
                else "",
            )
        return result

    return Server(
        f"commons/{agent.id}/{upstream.name}",
        version=COMMONS_VERSION,
        title=f"Commons · {agent.display_name} → {upstream.name}",
        instructions=(
            "You are connected through Commons, an arbitration gateway. Calls are evaluated "
            "against merchant policy that spans every agent acting on this customer, not just "
            "yours. A blocked call means another agent has already consumed the shared budget."
        ),
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )
