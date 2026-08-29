"""Upstream MCP connections — the client face of the proxy.

One long-lived connection per upstream, shared by every agent. That sharing is the
whole point: cross-agent state is only observable because every agent's traffic passes
through one process (IMPLEMENTATION_PLAN.md D1).
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack, suppress

import httpx2 as httpx
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.memory import create_client_server_memory_streams
from mcp.types import CallToolResult, Tool

from commons.config import UpstreamConfig

logger = logging.getLogger(__name__)


def _describe(exc: BaseException) -> str:
    """The cause, not the wrapper.

    MCP transports run in task groups, so a refused connection arrives as
    "ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)". That tells a
    merchant nothing; "ConnectError: All connection attempts failed" tells them their
    vendor is not running.
    """
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return f"{type(exc).__name__}: {exc}"[:200]


async def _stop(task: asyncio.Task) -> None:
    """Shut a memory upstream server task down rather than leaving it orphaned."""
    task.cancel()
    try:
        await task
    except BaseException:  # noqa: BLE001 - teardown, nothing left to salvage
        pass


class Upstream:
    """A live MCP client session against one real MCP server."""

    def __init__(self, cfg: UpstreamConfig) -> None:
        self.cfg = cfg
        self.session: ClientSession | None = None
        self._tools: list[Tool] | None = None
        # Low-volume workload; serialise to keep session state unambiguous.
        self._lock = asyncio.Lock()
        self.error: str | None = None
        self._task: asyncio.Task | None = None
        self._ready = asyncio.Event()
        self._closing = asyncio.Event()

    @property
    def name(self) -> str:
        return self.cfg.name

    async def _hold(self) -> None:
        """Own this connection for the life of the process, in one dedicated task.

        The transport is an anyio task group. Opening it on a stack shared with other
        upstreams, then discarding it when the handshake failed, unwound that group from
        the wrong scope: one unreachable vendor took the whole gateway down during
        startup, and the error surfaced as a CancelledError far from its cause.

        A cancel scope belongs to the task that entered it. Giving each vendor its own
        task means a vendor that refuses is just a vendor that refuses.
        """
        try:
            async with AsyncExitStack() as own:
                await self._connect(own)
                self.error = None
                self._ready.set()
                await self._closing.wait()
        except BaseException as exc:  # noqa: BLE001 - recorded, then reported on /health
            self.session = None
            self.error = _describe(exc)
        finally:
            self._ready.set()

    async def open(self, stack: AsyncExitStack) -> None:
        """Start the connection task and wait for it to succeed or fail."""
        self._task = asyncio.create_task(self._hold(), name=f"upstream-{self.name}")
        stack.push_async_callback(self.close)
        await self._ready.wait()
        if self.error:
            raise ConnectionError(self.error)

    async def close(self) -> None:
        self._closing.set()
        if self._task is not None:
            with suppress(BaseException):
                await asyncio.wait_for(asyncio.shield(self._task), timeout=5.0)

    async def _connect(self, stack: AsyncExitStack) -> None:
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
            # An MCP server object running in this process, spoken to over paired streams
            # rather than a socket. Used by the stress harness, where an HTTP hop per call
            # would be measuring uvicorn rather than Commons, and where a real vendor's
            # rate limits make load testing impossible.
            assert cfg.server_factory, f"upstream {cfg.name} has kind=memory but no server_factory"
            server = cfg.server_factory()
            client_streams, server_streams = await stack.enter_async_context(
                create_client_server_memory_streams()
            )
            read, write = client_streams

            # The server half has to be pumped by someone. Nothing else runs it, so this
            # task owns it for the lifetime of the pool.
            task = asyncio.create_task(
                server.run(
                    server_streams[0],
                    server_streams[1],
                    server.create_initialization_options(),
                ),
                name=f"memory-upstream-{cfg.name}",
            )
            stack.push_async_callback(_stop, task)
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
        self.failed: dict[str, str] = {}

    async def open_all(self, stack: AsyncExitStack) -> None:
        """Connect every vendor, and keep going if one refuses.

        A vendor being unreachable is not a reason for the gateway to fail to boot. On a
        first run the merchant has configured Razorpay and not yet stood up a messaging
        server, and a Commons that will not start until every vendor answers is a Commons
        they cannot try. The ones that did connect are governed; the rest are reported on
        /health so the gap is visible rather than silent.
        """
        for name, up in self.upstreams.items():
            try:
                await up.open(stack)
            except Exception as exc:  # noqa: BLE001 - report per vendor, do not abort boot
                self.failed[name] = str(exc)[:200]
                logger.error("upstream %s unavailable: %s", name, str(exc)[:200])

    def available(self):
        """The upstreams that actually connected."""
        return [up for name, up in self.upstreams.items() if name not in self.failed]

    async def add(self, cfg: UpstreamConfig, stack: AsyncExitStack) -> Upstream:
        """Connect a vendor while the gateway is running.

        Raises if it will not connect, so the caller can report the reason instead of
        registering something that does not work.
        """
        up = Upstream(cfg)
        self.upstreams[cfg.name] = up
        self.failed.pop(cfg.name, None)
        try:
            await up.open(stack)
        except Exception as exc:  # noqa: BLE001 - the caller reports this to the merchant
            self.failed[cfg.name] = str(exc)[:200]
            raise
        return up

    async def drop(self, name: str) -> None:
        up = self.upstreams.pop(name, None)
        self.failed.pop(name, None)
        if up is not None:
            await up.close()

    def get(self, name: str) -> Upstream:
        return self.upstreams[name]

    def __iter__(self):
        return iter(self.upstreams.values())
