"""Run the messaging MCP server as a standalone vendor.

    .venv/Scripts/python.exe mcp_servers/messaging/run.py --port 8788

It runs in its own process, on its own port, with no knowledge of Commons. Commons
connects to it exactly the way it connects to Razorpay's hosted server.
"""

from __future__ import annotations

import argparse
import logging
import os

import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from mcp_servers.messaging.server import Outbox, build_messaging_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)-28s %(message)s",
    datefmt="%H:%M:%S",
)


def create_app(outbox: Outbox | None = None) -> Starlette:
    box = outbox or Outbox()
    mcp_app = build_messaging_server(box).streamable_http_app(streamable_http_path="/mcp")

    async def health(_request):
        return JSONResponse({"service": "messaging", "delivered": len(box.deliveries)})

    async def outbox_view(_request):
        from dataclasses import asdict

        return JSONResponse([asdict(d) for d in box.deliveries])

    mcp_app.router.routes.append(Route("/health", health))
    mcp_app.router.routes.append(Route("/outbox", outbox_view))
    return mcp_app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.environ.get("MESSAGING_PORT", "8788")))
    # Loopback by default for the same reason as the gateway: this is a vendor holding
    # customer messages. The container overrides it because a container's loopback
    # reaches nothing but itself.
    parser.add_argument("--host", default=os.environ.get("MESSAGING_HOST", "127.0.0.1"))
    args = parser.parse_args()
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="warning")
