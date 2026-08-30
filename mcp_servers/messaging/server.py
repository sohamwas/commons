"""A messaging MCP server — the SECOND vendor.

Required, not decorative:

  1. Razorpay's MCP has no general messaging tools, so the most intuitive rule in the
     demo — "don't message a customer three times a day" — is unimplementable with
     Razorpay alone.
  2. Entity resolution only becomes interesting ACROSS servers. Inside Razorpay every
     call already carries a customer_id; joining two Razorpay calls is trivial. The hard
     part is recognising send_whatsapp(to: "+9198…") and create_payment_link(
     customer_contact: "9800…") are the same human. With one server the novel part
     evaporates.
  3. "Independently-built vendors" needs more than one vendor.

This server knows nothing about Commons, Razorpay, entities, or rules. It sends
messages. That is the point: Commons governs it through its published tool schema alone.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from mcp.server import Server, ServerRequestContext
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)

logger = logging.getLogger(__name__)

OUTBOX_PATH = Path("outbox.jsonl")


@dataclass
class Delivery:
    id: str
    channel: str
    to: str
    body: str
    kind: str
    sent_at: str
    subject: str | None = None
    template: str | None = None


@dataclass
class Outbox:
    """Where 'sent' messages go. Simulated delivery — nothing leaves the machine."""

    path: Path = OUTBOX_PATH
    deliveries: list[Delivery] = field(default_factory=list)

    def add(self, delivery: Delivery) -> None:
        self.deliveries.append(delivery)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(delivery)) + "\n")

    def clear(self) -> None:
        self.deliveries.clear()
        if self.path.exists():
            self.path.unlink()


TOOLS = [
    Tool(
        name="send_whatsapp",
        title="Send a WhatsApp message",
        description="Send a WhatsApp message to a customer's phone number.",
        input_schema={
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient phone number in any common format.",
                },
                "body": {"type": "string", "description": "Message text."},
                "kind": {
                    "type": "string",
                    "enum": ["promotional", "transactional"],
                    "description": "Promotional (marketing) or transactional (e.g. shipping update).",
                },
                "template": {"type": "string", "description": "Optional template name."},
            },
            "required": ["to", "body"],
        },
    ),
    Tool(
        name="send_email",
        title="Send an email",
        description="Send an email to a customer's email address.",
        input_schema={
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address."},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "kind": {"type": "string", "enum": ["promotional", "transactional"]},
                # send_whatsapp had this and send_email did not, which meant an agent
                # told to send under an approved template had no way to say so. Every
                # dispute email was therefore classified as marketing and flagged as
                # "promotional message to a customer in dispute" — four identical false
                # positives, and every violation in the run was this one bug.
                "template": {
                    "type": "string",
                    "description": "Name of a merchant-approved template, if this message uses one.",
                },
            },
            "required": ["to", "body"],
        },
    ),
]


def build_messaging_server(outbox: Outbox | None = None, clock=None) -> Server:
    box = outbox or Outbox()
    now = clock or (lambda: datetime.now(timezone.utc))
    counter = {"n": 0}

    async def on_list_tools(
        ctx: ServerRequestContext, params: PaginatedRequestParams | None
    ) -> ListToolsResult:
        return ListToolsResult(tools=TOOLS)

    async def on_call_tool(
        ctx: ServerRequestContext, params: CallToolRequestParams
    ) -> CallToolResult:
        args = dict(params.arguments or {})
        if params.name not in {"send_whatsapp", "send_email"}:
            return CallToolResult(
                content=[TextContent(type="text", text=f"unknown tool: {params.name}")],
                is_error=True,
            )

        to = str(args.get("to", "")).strip()
        if not to:
            return CallToolResult(
                content=[TextContent(type="text", text="'to' is required")], is_error=True
            )

        counter["n"] += 1
        delivery = Delivery(
            id=f"msg_{counter['n']:06d}",
            channel="whatsapp" if params.name == "send_whatsapp" else "email",
            to=to,
            body=str(args.get("body", "")),
            kind=str(args.get("kind", "promotional")),
            sent_at=now().isoformat(timespec="milliseconds"),
            subject=args.get("subject"),
            template=args.get("template"),
        )
        box.add(delivery)
        logger.info("delivered %s %s -> %s", delivery.id, delivery.channel, delivery.to)

        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(asdict(delivery)))]
        )

    return Server(
        "messaging",
        version="1.0.0",
        title="Messaging",
        instructions="Send WhatsApp and email messages to customers.",
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )
