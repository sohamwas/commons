"""Upstream MCP connections — the client face of the proxy.

One long-lived connection per upstream, shared by every agent. That sharing is the
whole point: cross-agent state is only observable because every agent's traffic passes
through one process (IMPLEMENTATION_PLAN.md D1).
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack

import httpx2 as httpx
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, Tool

from commons.config import UpstreamConfig

logger = logging.getLogger(__name__)


class Upstream:
    """A live MCP client session against one real MCP server."""

    def __init__(self, cfg: UpstreamConfig) -> None:
        self.cfg = cfg
        self.session: ClientSession | None = None
        self._tools: list[Tool] | None = None
        # Low-volume workload; serialise to keep session state unambiguous.
        self._lock = asyncio.Lock()

    @property
    def name(self) -> str:
        return self.cfg.name

    async def open(self, stack: AsyncExitStack) -> None:
        cfg = self.cfg
        if cfg.kind == "http":
            assert cfg.url
            http_client = await stack.enter_async_context(
                httpx.AsyncClient(headers=cfg.headers, timeout=60.0)
            )
            read, write = await stack.enter_async_context(
                streamable_http_client(cfg.url, http_client=http_client)
            )
        elif cfg.kind == "stdio":
            assert cfg.command
            read, write = await stack.enter_async_context(
                stdio_client(
                    StdioServerParameters(command=cfg.command, args=cfg.args, env=cfg.env)
                )
            )
        elif cfg.kind == "memory":
            # Day 4, with the messaging server. Deliberately not written before there is
            # something real to connect it to.
            raise NotImplementedError("memory upstreams land with the messaging server (Day 4)")
        else:  # pragma: no cover
            raise ValueError(f"unknown upstream kind: {cfg.kind}")

        self.session = await stack.enter_async_context(ClientSession(read, write))
        init = await self.session.initialize()
        logger.info(
            "upstream %s connected: %s v%s (%s)",
            cfg.name,
            init.server_info.name,
            init.server_info.version,
            cfg.kind,
        )

    async def list_tools(self) -> list[Tool]:
        """Upstream catalogues are static for a run; fetch once."""
        if self._tools is None:
            assert self.session, f"upstream {self.name} not connected"
            async with self._lock:
                if self._tools is None:
                    self._tools = list((await self.session.list_tools()).tools)
        return self._tools

    async def call_tool(self, name: str, arguments: dict) -> CallToolResult:
        assert self.session, f"upstream {self.name} not connected"
        async with self._lock:
            return await self.session.call_tool(name, arguments)


class UpstreamPool:
    def __init__(self, configs: dict[str, UpstreamConfig]) -> None:
        self.upstreams = {name: Upstream(cfg) for name, cfg in configs.items()}

    async def open_all(self, stack: AsyncExitStack) -> None:
        for up in self.upstreams.values():
            await up.open(stack)

    def get(self, name: str) -> Upstream:
        return self.upstreams[name]

    def __iter__(self):
        return iter(self.upstreams.values())
