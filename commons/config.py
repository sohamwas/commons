"""Upstream MCP server configuration.

An upstream is a real MCP server that Commons forwards approved calls to.
Three transports are supported (IMPLEMENTATION_PLAN.md D3):

  http   — Razorpay's remote server, https://mcp.razorpay.com/mcp
  stdio  — a local binary (the §7 R1 fallback: razorpay-mcp-server built from Go)
  memory — an in-process Server object (our messaging server; the bundled fake Razorpay)

Swapping transports is a config change, never a code change. That is what makes the
two-tier setup of handoff §15.4 (`commons demo` vs `commons demo --real`) cheap.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field
from typing import Any, Literal

from dotenv import load_dotenv

load_dotenv(dotenv_path=".env")

RAZORPAY_MCP_URL = "https://mcp.razorpay.com/mcp"

Kind = Literal["http", "stdio", "memory"]


@dataclass(frozen=True)
class UpstreamConfig:
    name: str
    kind: Kind
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    server_factory: Any = None  # callable -> mcp.server.Server, for kind="memory"


def _razorpay_basic_auth() -> str:
    """Razorpay authenticates the remote MCP with base64(key_id:key_secret)."""
    key_id = os.environ.get("RAZORPAY_KEY_ID", "").strip()
    secret = os.environ.get("RAZORPAY_KEY_SECRET", "").strip()
    if not key_id or not secret:
        raise RuntimeError("RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET missing from .env")
    if not key_id.startswith("rzp_test_"):
        # Commons forwards real write calls. Refuse to point it at a live account by accident.
        raise RuntimeError(
            "Refusing to start: RAZORPAY_KEY_ID is not a test key (expected rzp_test_ prefix)."
        )
    return "Basic " + base64.b64encode(f"{key_id}:{secret}".encode()).decode()


def razorpay_remote() -> UpstreamConfig:
    return UpstreamConfig(
        name="razorpay",
        kind="http",
        url=RAZORPAY_MCP_URL,
        headers={"Authorization": _razorpay_basic_auth()},
    )


def razorpay_local_stdio(binary_path: str) -> UpstreamConfig:
    """§7 R1 fallback — only needed if the remote server ever drops a tool we depend on."""
    return UpstreamConfig(
        name="razorpay",
        kind="stdio",
        command=binary_path,
        args=["stdio"],
        env={
            "RAZORPAY_KEY_ID": os.environ.get("RAZORPAY_KEY_ID", ""),
            "RAZORPAY_KEY_SECRET": os.environ.get("RAZORPAY_KEY_SECRET", ""),
        },
    )


MESSAGING_MCP_URL = "http://127.0.0.1:8788/mcp"


def messaging_local() -> UpstreamConfig:
    """The second vendor. Runs in its own process on its own port, and knows nothing
    about Commons — Commons reaches it exactly as it reaches Razorpay's hosted server."""
    return UpstreamConfig(name="messaging", kind="http", url=MESSAGING_MCP_URL)


def default_upstreams() -> dict[str, UpstreamConfig]:
    return {"razorpay": razorpay_remote(), "messaging": messaging_local()}
