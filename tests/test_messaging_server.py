"""The messaging server — the second vendor.

It knows nothing about Commons, entities, or rules. These tests treat it exactly as a
third-party vendor's server: drive it through its published MCP interface only.
"""

from __future__ import annotations

import json

import pytest
from mcp import Client

from mcp_servers.messaging.server import Outbox, build_messaging_server


@pytest.fixture()
def outbox(tmp_path):
    return Outbox(path=tmp_path / "outbox.jsonl")


async def test_exposes_two_messaging_tools(outbox):
    async with Client(build_messaging_server(outbox)) as client:
        tools = sorted(t.name for t in (await client.list_tools()).tools)
    assert tools == ["send_email", "send_whatsapp"]


async def test_sending_whatsapp_records_a_delivery(outbox):
    async with Client(build_messaging_server(outbox)) as client:
        result = await client.call_tool(
            "send_whatsapp",
            {"to": "+919800000021", "body": "Still interested? 10% off.", "kind": "promotional"},
        )
    payload = json.loads(
        "".join(c.text for c in result.content if getattr(c, "type", None) == "text")
    )
    assert payload["channel"] == "whatsapp"
    assert payload["to"] == "+919800000021"
    assert len(outbox.deliveries) == 1


async def test_missing_recipient_is_an_error(outbox):
    async with Client(build_messaging_server(outbox)) as client:
        result = await client.call_tool("send_whatsapp", {"body": "hi"})
    assert result.is_error
    assert outbox.deliveries == []


async def test_outbox_persists_to_disk(outbox):
    async with Client(build_messaging_server(outbox)) as client:
        await client.call_tool("send_email", {"to": "priya@example.com", "body": "hello"})
    lines = outbox.path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["channel"] == "email"


def test_the_server_has_no_dependency_on_commons():
    """If this vendor had to be Commons-aware, the whole "works with third-party agents
    you cannot inspect" claim would be false.

    Checks imports rather than prose: the docstrings explain the vendor's role in the
    project, which is fine — what must not exist is a code dependency.
    """
    import ast
    import inspect

    import mcp_servers.messaging.server as module

    tree = ast.parse(inspect.getsource(module))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    assert not any(name.split(".")[0] == "commons" for name in imported), imported


async def test_email_subject_is_recorded(outbox):
    """The tool schema advertises `subject`; a field a vendor advertises and then
    silently drops is exactly the kind of gap Commons would be blamed for."""
    async with Client(build_messaging_server(outbox)) as client:
        await client.call_tool(
            "send_email",
            {"to": "priya@example.com", "subject": "Your cart", "body": "10% off"},
        )
    assert outbox.deliveries[0].subject == "Your cart"
