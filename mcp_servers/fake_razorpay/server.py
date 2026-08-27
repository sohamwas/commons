"""An in-memory stand-in for Razorpay's remote MCP server.

Built for stress testing, after the loyalty example hit `test mode limit of 30 reached
for payment_link` on the fifth customer. Razorpay's test account is rate-limited, as it
should be, which makes it useless as a load target. commons/config.py already documented
a "bundled fake Razorpay" for the `memory` transport; this is it.

The tool NAMES and SCHEMAS mirror the remote server's, because that is the only contract
Commons depends on. In particular the input schemas are FLAT (`customer_contact`, not
`customer.contact`) while the responses are nested, which is the distinction
semantics/manifests/razorpay.yaml is written against. Getting that wrong here would make
the stress test pass against a shape that does not exist.

Nothing here knows what Commons is.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

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


@dataclass
class FakeState:
    payment_links: dict[str, dict] = field(default_factory=dict)
    orders: dict[str, dict] = field(default_factory=dict)
    counter: int = 0

    def next_id(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}_{self.counter:08d}"


def _ok(payload: dict) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(payload))])


def _err(message: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=message)], is_error=True)


TOOLS = [
    Tool(
        name="create_payment_link",
        title="Create a payment link",
        description="Create a payment link and optionally notify the customer.",
        input_schema={
            "type": "object",
            "properties": {
                "amount": {"type": "integer", "description": "Amount in paise."},
                "currency": {"type": "string"},
                "description": {"type": "string"},
                "customer_name": {"type": "string"},
                "customer_email": {"type": "string"},
                "customer_contact": {"type": "string"},
                "notify_sms": {"type": "boolean"},
                "notify_email": {"type": "boolean"},
                "reference_id": {"type": "string"},
                "notes": {"type": "object", "description": "Merchant key/value record."},
            },
            "required": ["amount", "currency"],
        },
    ),
    Tool(
        name="payment_link_notify",
        title="Notify a customer about a payment link",
        description="Send a payment link to the customer by SMS or email.",
        input_schema={
            "type": "object",
            "properties": {
                "payment_link_id": {"type": "string"},
                "medium": {"type": "string", "enum": ["sms", "email"]},
            },
            "required": ["payment_link_id", "medium"],
        },
    ),
    Tool(
        name="fetch_payment_link",
        title="Fetch a payment link",
        description="Fetch a payment link by id.",
        input_schema={
            "type": "object",
            "properties": {"payment_link_id": {"type": "string"}},
            "required": ["payment_link_id"],
        },
    ),
    Tool(
        name="fetch_order",
        title="Fetch an order",
        description="Fetch an order by id.",
        input_schema={
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    ),
    Tool(
        name="update_order",
        title="Update an order",
        description="Update an order's notes, for example to restrict it to prepaid.",
        input_schema={
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "notes": {"type": "object"},
            },
            "required": ["order_id", "notes"],
        },
    ),
    Tool(
        name="fetch_all_orders",
        title="Fetch all orders",
        description="List recent orders.",
        input_schema={"type": "object", "properties": {"count": {"type": "integer"}}},
    ),
    Tool(
        name="fetch_all_payments",
        title="Fetch all payments",
        description="List recent payments.",
        input_schema={"type": "object", "properties": {"count": {"type": "integer"}}},
    ),
    Tool(
        name="fetch_payment",
        title="Fetch a payment",
        description="Fetch a payment by id.",
        input_schema={
            "type": "object",
            "properties": {"payment_id": {"type": "string"}},
            "required": ["payment_id"],
        },
    ),
    Tool(
        name="fetch_refund",
        title="Fetch refunds",
        description="List refunds.",
        input_schema={"type": "object", "properties": {"count": {"type": "integer"}}},
    ),
    Tool(
        name="fetch_specific_refund_for_payment",
        title="Fetch a refund for a payment",
        description="Fetch one refund belonging to a payment.",
        input_schema={
            "type": "object",
            "properties": {"payment_id": {"type": "string"}, "refund_id": {"type": "string"}},
            "required": ["payment_id", "refund_id"],
        },
    ),
]

TOOL_NAMES = {t.name for t in TOOLS}


def build_fake_razorpay(state: FakeState | None = None, clock=None) -> Server:
    st = state or FakeState()
    now = clock or (lambda: datetime.now(timezone.utc))

    async def on_list_tools(
        ctx: ServerRequestContext, params: PaginatedRequestParams | None
    ) -> ListToolsResult:
        return ListToolsResult(tools=TOOLS)

    async def on_call_tool(
        ctx: ServerRequestContext, params: CallToolRequestParams
    ) -> CallToolResult:
        args = dict(params.arguments or {})
        name = params.name

        if name not in TOOL_NAMES:
            return _err(f"unknown tool: {name}")

        if name == "create_payment_link":
            if not args.get("amount"):
                return _err("amount is required")
            link_id = st.next_id("plink")
            # Response shape is NESTED even though the input was flat. This is what
            # payment_link_notify's upstream_lookup in the manifest reads back.
            record = {
                "id": link_id,
                "amount": args.get("amount"),
                "currency": args.get("currency", "INR"),
                "description": args.get("description", ""),
                "reference_id": args.get("reference_id"),
                "notes": args.get("notes") or {},
                "short_url": f"https://rzp.io/i/{link_id}",
                "status": "created",
                "customer": {
                    "name": args.get("customer_name"),
                    "email": args.get("customer_email"),
                    "contact": args.get("customer_contact"),
                },
                "created_at": now().isoformat(timespec="seconds"),
            }
            st.payment_links[link_id] = record
            return _ok(record)

        if name == "fetch_payment_link":
            record = st.payment_links.get(str(args.get("payment_link_id")))
            return _ok(record) if record else _err("payment link not found")

        if name == "payment_link_notify":
            link_id = str(args.get("payment_link_id"))
            if link_id not in st.payment_links:
                return _err("payment link not found")
            return _ok({"success": True, "payment_link_id": link_id, "medium": args.get("medium")})

        if name == "fetch_order":
            order_id = str(args.get("order_id"))
            record = st.orders.setdefault(
                order_id,
                {"id": order_id, "amount": 249900, "currency": "INR", "status": "created", "notes": {}},
            )
            return _ok(record)

        if name == "update_order":
            order_id = str(args.get("order_id"))
            record = st.orders.setdefault(
                order_id,
                {"id": order_id, "amount": 249900, "currency": "INR", "status": "created", "notes": {}},
            )
            record["notes"] = {**record.get("notes", {}), **(args.get("notes") or {})}
            return _ok(record)

        if name == "fetch_all_orders":
            return _ok({"count": len(st.orders), "items": list(st.orders.values())})

        # The remaining reads are not interesting to any rule; they exist so an agent's
        # allowlist resolves and its calls are still attributed to the customer.
        return _ok({"count": 0, "items": []})

    return Server(
        "fake-razorpay",
        version="0.1.0",
        title="Fake Razorpay",
        instructions="An in-memory stand-in for Razorpay's MCP server, for load testing.",
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )
