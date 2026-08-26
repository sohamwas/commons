"""Commons proxy — the ASGI application.

Mounts one MCP endpoint per (agent, upstream) pair:

    /mcp/cart-recovery/razorpay
    /mcp/subscription-recovery/razorpay
    ...

An agent is onboarded by pointing it at its own Commons URL instead of the vendor's —
the one-line config change on the Connect screen:

    - "razorpay": { "url": "https://mcp.razorpay.com/mcp" }
    + "razorpay": { "url": "https://commons.local/mcp/cart-recovery/razorpay" }
"""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime, timezone

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from commons.config import UpstreamConfig, default_upstreams
from commons.identity.resolver import IdentityResolver
from commons.ledger.db import Ledger
from commons.proxy.face import COMMONS_VERSION, build_face
from commons.proxy.registry import AGENTS
from commons.proxy.upstream import UpstreamPool
from commons.rules.engine import RuleEngine
from commons.semantics.manifest import load_manifests

logger = logging.getLogger(__name__)


class PathDispatch:
    """Dispatch exact MCP endpoint paths to their sub-apps; everything else falls through.

    Starlette's Mount is not usable here: its path regex requires the remainder to begin
    with "/", so a request to the bare mount path never matches and the parent router
    answers 307. MCP clients do not follow that redirect — they surface it as
    "Unexpected content type". Since the endpoint URL is the product's entire onboarding
    step, it has to work without a trailing slash, so we route these paths ourselves.
    """

    def __init__(self, table: dict[str, object], fallback) -> None:
        self.table = table
        self.fallback = fallback

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            path = scope.get("path", "")
            sub = self.table.get(path.rstrip("/") or "/")
            if sub is not None:
                # The sub-app serves its endpoint at "/".
                scope = {**scope, "path": "/", "raw_path": b"/", "root_path": path.rstrip("/")}
                await sub(scope, receive, send)
                return
        # lifespan and everything else (e.g. /health) goes to the Starlette app
        await self.fallback(scope, receive, send)


class Clock:
    """The gateway's notion of "now".

    Defaults to the wall clock, which is what a real deployment uses. A simulation
    drives it forward via POST /admin/clock so that a 30-day month can play out in a
    minute and a "once per 24 hours" rule still means 24 simulated hours.
    """

    def __init__(self) -> None:
        self._override: datetime | None = None

    def now(self) -> datetime:
        return self._override or datetime.now(timezone.utc)

    def set(self, when: datetime | None) -> None:
        self._override = when

    @property
    def simulated(self) -> bool:
        return self._override is not None


def create_app(
    upstream_configs: dict[str, UpstreamConfig] | None = None,
    db_path: str = "commons.db",
    mode: str = "OBSERVE",
):
    pool = UpstreamPool(upstream_configs or default_upstreams())
    ledger = Ledger(db_path)
    resolver = IdentityResolver(ledger)
    manifests = load_manifests()
    engine = RuleEngine.load()
    clock = Clock()

    # Build every (agent, upstream) face up front. Each is a full Starlette sub-app with
    # its own session manager, so its lifespan must be entered explicitly — nothing runs
    # the lifespan of a sub-app for you.
    table: dict[str, object] = {}
    sub_apps: list[Starlette] = []
    endpoints: list[str] = []

    for agent in AGENTS.values():
        for upstream in pool:
            if not agent.allowed(upstream.name):
                continue  # this agent has no business with this upstream at all
            face = build_face(
                agent,
                upstream,
                ledger,
                resolver,
                manifests.get(upstream.name),
                engine=engine,
                mode=mode,
                clock=clock.now,
            )
            sub = face.streamable_http_app(streamable_http_path="/")
            path = f"/mcp/{agent.id}/{upstream.name}"
            table[path] = sub
            sub_apps.append(sub)
            endpoints.append(path)

    async def health(_request):
        return JSONResponse(
            {
                "service": "commons",
                "version": COMMONS_VERSION,
                "mode": mode,
                "run_id": ledger.run_id,
                "upstreams": [u.name for u in pool],
                "manifests": {n: len(m.tools) for n, m in manifests.items()},
                "rules": [r.id for r in engine.rules],
                "endpoints": endpoints,
            }
        )

    async def seed_entities(request):
        """Declare who the merchant's customers are.

        This is the mechanism that merges different KINDS of handle. Commons never
        infers that a phone and an email are one person; the merchant states it, once,
        from the customer list they already have. In the simulation the world does the
        stating; in production it would be a sync from the merchant's own database.

        POST /admin/entities
        {"entities": [{"ref": "cust_4471", "display_name": "Priya S.",
                       "handles": {"phone": "...", "email": "...", "customer_id": "..."},
                       "state": {"dispute_status": "none"}}]}
        """
        body = await request.json()
        mapping: dict[str, str] = {}
        for item in body.get("entities", []):
            handles = item.get("handles") or {}
            ref = item.get("ref") or handles.get("customer_id") or item.get("display_name", "")
            entity_id = ledger.create_entity(item.get("display_name") or ref)
            resolver.declare(entity_id, handles, source="merchant-declared")
            for key, value in (item.get("state") or {}).items():
                ledger.set_state(entity_id, key, value)
            mapping[ref] = entity_id
        logger.info("seeded %d entities", len(mapping))
        return JSONResponse({"seeded": len(mapping), "entities": mapping})

    async def start_run(request):
        """Begin a new run in the ledger.

        A run is one simulated month, not one proxy lifetime. Without this, two
        successive runs against the same proxy share a run_id and their results are
        summed — which silently doubles every headline number.
        """
        body = await request.json() if await request.body() else {}
        run_id = ledger.start_run(
            mode=mode, seed=body.get("seed"), notes=body.get("notes", "")
        )
        logger.info("started run %s", run_id)
        return JSONResponse({"run_id": run_id, "mode": mode})

    async def set_clock(request):
        """Move simulated time. POST /admin/clock {"now": "<iso8601>"} (null to reset)."""
        body = await request.json()
        raw = body.get("now")
        clock.set(datetime.fromisoformat(raw) if raw else None)
        return JSONResponse({"now": clock.now().isoformat(), "simulated": clock.simulated})

    async def set_state(request):
        """Update entity state the rules read, e.g. a dispute opening mid-run.

        POST /admin/state {"ref": "cust_4471", "key": "dispute_status", "value": "open"}
        `ref` is any handle Commons already knows: customer_id, phone or email.
        """
        body = await request.json()
        ref, key, value = body.get("ref"), body["key"], body.get("value")
        entity_id = body.get("entity_id")
        if entity_id is None:
            for namespace in ("customer_id", "phone", "email"):
                found, _ = resolver.resolve_existing(namespace, ref)
                if found:
                    entity_id = found
                    break
        if entity_id is None:
            return JSONResponse({"error": f"unknown entity: {ref}"}, status_code=404)
        ledger.set_state(entity_id, key, value)
        return JSONResponse({"entity_id": entity_id, key: value})

    async def list_entities(_request):
        rows = ledger.conn.execute(
            "SELECT id, display_name FROM entity ORDER BY id"
        ).fetchall()
        return JSONResponse(
            [
                {
                    "id": r["id"],
                    "display_name": r["display_name"],
                    "handles": ledger.identities_of(r["id"]),
                    "state": ledger.state_of(r["id"]),
                }
                for r in rows
            ]
        )

    @asynccontextmanager
    async def lifespan(_app: Starlette):
        async with AsyncExitStack() as stack:
            await pool.open_all(stack)
            for sub in sub_apps:
                await stack.enter_async_context(sub.router.lifespan_context(sub))
            run_id = ledger.start_run(mode=mode, notes="proxy session")
            logger.info("commons ready - %d endpoints, mode=%s, run=%s", len(endpoints), mode, run_id)
            for path in endpoints:
                logger.info("  %s", path)
            try:
                yield
            finally:
                ledger.end_run()

    base = Starlette(
        routes=[
            Route("/health", health),
            Route("/admin/entities", seed_entities, methods=["POST"]),
            Route("/admin/entities", list_entities, methods=["GET"]),
            Route("/admin/run", start_run, methods=["POST"]),
            Route("/admin/clock", set_clock, methods=["POST"]),
            Route("/admin/state", set_state, methods=["POST"]),
        ],
        lifespan=lifespan,
    )
    return PathDispatch(table, base)
