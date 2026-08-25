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

import json
import logging
import time

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
) -> Server:
    """An MCP server that presents `upstream` to `agent`, mediated by Commons."""

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
        # DECISION POINT — Day 3 evaluates the ruleset here and returns
        # ALLOW / DEFER / BLOCK. In OBSERVE mode the decision is recorded and the
        # call forwarded anyway; in ENFORCE mode it is honoured. Same engine, same
        # code path — the mode changes what happens on this line and nothing else.
        # ------------------------------------------------------------------
        decision = "ALLOW"

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
            decision=decision,
            forwarded=0,
            args_json=args,
        )

        if decision == "BLOCK":
            ledger.update_call(call_id, latency_ms=int((time.perf_counter() - started) * 1000))
            return _denied("Commons: blocked by merchant policy.")

        result = await upstream.call_tool(params.name, args)
        text = _result_text(result)

        ledger.update_call(
            call_id,
            forwarded=1,
            result_json=text,
            is_error=1 if result.is_error else 0,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

        logger.info(
            "%s agent=%s tool=%s action=%s entity=%s%s",
            decision,
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
