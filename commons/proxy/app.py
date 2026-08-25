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

    base = Starlette(routes=[Route("/health", health)], lifespan=lifespan)
    return PathDispatch(table, base)
