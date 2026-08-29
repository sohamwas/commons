"""Which agents exist, and what each one may call.

This is the whole of what Commons knows about an agent: an id, a name, and a tool
allowlist per vendor. There is no prompt, no model, no behaviour. That is deliberate —
Commons governs agents whose source it never sees, so it cannot depend on knowing what
they do, only on what they are permitted to touch.

The registry is a FILE, not source code. A merchant adding an agent should not be editing
Python and restarting a gateway their agents are connected to.

The allowlist is also least privilege in practice: Razorpay's remote MCP publishes 42
tools and a given agent usually needs three. That is both a smaller attack surface and a
smaller system prompt, which is the same decision twice.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

DEFAULT_PATH = Path("agents.yaml")

# Every tool the vendor publishes.
#
# This is the DEFAULT, because narrowing an allowlist is a security decision and putting
# one in front of a merchant before they have seen the thing work is the wrong order.
# Commons governs an agent holding all 42 tools exactly as well as one holding three: the
# rules are about what happens to a CUSTOMER, not about which tool did it.
#
# Narrowing is a real second layer and worth doing, just not by guesswork at onboarding.
# Once an agent has run, the ledger knows which tools it actually called, so the suggestion
# can come from evidence.
ALL = "*"

# Agent ids become URL path segments, so they have to survive being one.
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


class InvalidAgent(ValueError):
    """The submitted agent cannot be registered, with a reason a merchant can act on."""


@dataclass(frozen=True)
class AgentSpec:
    id: str
    display_name: str
    # upstream name -> tools this agent may call on it
    tools: dict[str, tuple[str, ...]]

    def allowed(self, upstream: str) -> tuple[str, ...]:
        return self.tools.get(upstream, ())

    def takes_all(self, upstream: str) -> bool:
        return ALL in self.tools.get(upstream, ())

    def permits(self, upstream: str, tool: str) -> bool:
        names = self.tools.get(upstream, ())
        return ALL in names or tool in names

    def as_dict(self) -> dict:
        return {
            "display_name": self.display_name,
            "tools": {up: list(names) for up, names in self.tools.items()},
        }


def parse_agent(agent_id: str, raw: dict, known_upstreams: set[str] | None = None) -> AgentSpec:
    """Validate one agent definition, refusing rather than half-registering it."""
    if not isinstance(agent_id, str) or not ID_PATTERN.match(agent_id):
        raise InvalidAgent(
            f"'{agent_id}' is not a usable id. Use lowercase letters, digits and hyphens, "
            "starting with a letter or digit."
        )

    body = raw or {}
    tools_raw = body.get("tools") or {}

    # The easy path: name the vendors and take everything they publish.
    #   {"id": "cart-recovery", "vendors": ["razorpay"]}
    if not tools_raw and body.get("vendors"):
        tools_raw = {str(name): [ALL] for name in body["vendors"]}

    if not isinstance(tools_raw, dict) or not tools_raw:
        raise InvalidAgent(f"'{agent_id}' names no vendors, so it would have nothing to call.")

    tools: dict[str, tuple[str, ...]] = {}
    for upstream, names in tools_raw.items():
        if known_upstreams is not None and upstream not in known_upstreams:
            raise InvalidAgent(
                f"'{agent_id}' names vendor '{upstream}', which is not configured. "
                f"Configured vendors: {', '.join(sorted(known_upstreams)) or 'none'}."
            )
        if isinstance(names, str):
            names = [names]
        if not isinstance(names, (list, tuple)) or not names:
            # An empty list means the whole vendor, not nothing. "Nothing" is what
            # leaving the vendor out is for.
            names = [ALL]
        tools[upstream] = tuple(str(n).strip() for n in names if str(n).strip()) or (ALL,)

    return AgentSpec(
        id=agent_id,
        display_name=str((raw or {}).get("display_name") or agent_id),
        tools=tools,
    )


class AgentRegistry:
    """The agent list, backed by a YAML file the merchant can also edit by hand."""

    def __init__(self, path: Path | str = DEFAULT_PATH) -> None:
        self.path = Path(path)
        self.agents: dict[str, AgentSpec] = {}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.agents = {}
            return
        raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        agents = raw.get("agents") or {}
        parsed: dict[str, AgentSpec] = {}
        for agent_id, body in agents.items():
            try:
                parsed[agent_id] = parse_agent(agent_id, body)
            except InvalidAgent as exc:
                # One bad entry must not stop the gateway from serving the others.
                logger.error("skipping agent in %s: %s", self.path, exc)
        self.agents = parsed
        logger.info("registry: %d agents from %s", len(parsed), self.path)

    def save(self) -> None:
        body = {"agents": {a.id: a.as_dict() for a in self.agents.values()}}
        self.path.write_text(
            "# Agents registered with Commons. Managed from the Connect page, and safe to\n"
            "# edit by hand. Each entry is an id and the tools that agent may call.\n\n"
            + yaml.safe_dump(body, sort_keys=True, default_flow_style=False),
            encoding="utf-8",
        )

    def add(self, spec: AgentSpec) -> AgentSpec:
        self.agents[spec.id] = spec
        self.save()
        return spec

    def remove(self, agent_id: str) -> bool:
        if agent_id not in self.agents:
            return False
        del self.agents[agent_id]
        self.save()
        return True

    def get(self, agent_id: str) -> AgentSpec | None:
        return self.agents.get(agent_id)

    def values(self):
        return self.agents.values()

    def __len__(self) -> int:
        return len(self.agents)

    def __iter__(self):
        return iter(self.agents.values())
