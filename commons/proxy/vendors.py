"""Which MCP servers Commons forwards to.

A vendor is any MCP server: a hosted one, something running on the merchant's own
machine, anything that speaks the protocol. The list used to be two entries hardcoded in
config.py, which quietly made Commons a Razorpay-and-messaging tool rather than an
arbitration layer for whatever a merchant happens to use.

Like the agent registry, this is a FILE the admin API writes and a merchant can edit.

SECRETS: a header value written as "env:NAME" is read from the environment at connect
time, so tokens stay in .env and never land in a file that is easier to leak. Literal
values are allowed because sometimes a header is not a secret, but the placeholder is
what the UI writes.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from commons.config import UpstreamConfig, razorpay_remote

logger = logging.getLogger(__name__)

DEFAULT_PATH = Path("vendors.yaml")

# Vendor names become URL path segments, exactly like agent ids.
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")

ENV_PREFIX = "env:"


class InvalidVendor(ValueError):
    """The submitted vendor cannot be registered, with a reason a merchant can act on."""


@dataclass
class VendorDef:
    name: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    # Set for vendors Commons knows how to authenticate itself, so the merchant does not
    # have to hand-build a header from keys that are already in .env.
    auth: str | None = None

    def as_dict(self) -> dict:
        body: dict = {"url": self.url}
        if self.headers:
            body["headers"] = dict(self.headers)
        if self.auth:
            body["auth"] = self.auth
        return body

    def to_upstream(self) -> UpstreamConfig:
        if self.auth == "razorpay":
            return razorpay_remote()
        resolved = {}
        for key, value in self.headers.items():
            if isinstance(value, str) and value.startswith(ENV_PREFIX):
                env_name = value[len(ENV_PREFIX):].strip()
                resolved[key] = os.environ.get(env_name, "").strip()
                if not resolved[key]:
                    raise InvalidVendor(
                        f"'{self.name}' expects header {key} from ${env_name}, "
                        "which is not set in .env"
                    )
            else:
                resolved[key] = value
        return UpstreamConfig(name=self.name, kind="http", url=self.url, headers=resolved)


def parse_vendor(name: str, raw: dict) -> VendorDef:
    if not isinstance(name, str) or not NAME_PATTERN.match(name):
        raise InvalidVendor(
            f"'{name}' is not a usable vendor name. Use lowercase letters, digits and "
            "hyphens, starting with a letter or digit."
        )
    body = raw or {}
    auth = body.get("auth")
    url = str(body.get("url") or "").strip()

    if auth == "razorpay":
        return VendorDef(name=name, url=url or "https://mcp.razorpay.com/mcp", auth=auth)

    if not url.startswith(("http://", "https://")):
        raise InvalidVendor(f"'{name}' needs an http or https MCP URL.")

    headers = body.get("headers") or {}
    if not isinstance(headers, dict):
        raise InvalidVendor(f"'{name}' has headers that are not a mapping.")

    return VendorDef(
        name=name, url=url, headers={str(k): str(v) for k, v in headers.items()}
    )


def seed_defaults() -> dict[str, VendorDef]:
    """What a first run starts with.

    Razorpay only if its keys are present, because an entry that cannot authenticate is
    worse than no entry: the gateway starts, reports a vendor as unavailable, and the
    merchant has to work out that the cause is an empty .env.
    """
    vendors: dict[str, VendorDef] = {}
    if os.environ.get("RAZORPAY_KEY_ID", "").strip():
        vendors["razorpay"] = VendorDef(
            name="razorpay", url="https://mcp.razorpay.com/mcp", auth="razorpay"
        )
    return vendors


class VendorRegistry:
    """The vendor list, backed by a YAML file the merchant can also edit by hand."""

    def __init__(self, path: Path | str = DEFAULT_PATH) -> None:
        self.path = Path(path)
        self.vendors: dict[str, VendorDef] = {}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.vendors = seed_defaults()
            if self.vendors:
                self.save()
            return
        raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        parsed: dict[str, VendorDef] = {}
        for name, body in (raw.get("vendors") or {}).items():
            try:
                parsed[name] = parse_vendor(name, body)
            except InvalidVendor as exc:
                # One bad entry must not stop the gateway from reaching the others.
                logger.error("skipping vendor in %s: %s", self.path, exc)
        self.vendors = parsed
        logger.info("vendors: %d from %s", len(parsed), self.path)

    def save(self) -> None:
        body = {"vendors": {v.name: v.as_dict() for v in self.vendors.values()}}
        self.path.write_text(
            "# MCP servers Commons forwards to. Managed from the Connect page, and safe\n"
            "# to edit by hand. Write a secret header as env:NAME to read it from .env\n"
            "# rather than storing it here.\n\n"
            + yaml.safe_dump(body, sort_keys=True, default_flow_style=False),
            encoding="utf-8",
        )

    def add(self, vendor: VendorDef) -> VendorDef:
        self.vendors[vendor.name] = vendor
        self.save()
        return vendor

    def remove(self, name: str) -> bool:
        if name not in self.vendors:
            return False
        del self.vendors[name]
        self.save()
        return True

    def get(self, name: str) -> VendorDef | None:
        return self.vendors.get(name)

    def upstream_configs(self) -> dict[str, UpstreamConfig]:
        configs: dict[str, UpstreamConfig] = {}
        for name, vendor in self.vendors.items():
            try:
                configs[name] = vendor.to_upstream()
            except InvalidVendor as exc:
                logger.error("vendor %s not configurable: %s", name, exc)
        return configs

    def __len__(self) -> int:
        return len(self.vendors)

    def __iter__(self):
        return iter(self.vendors.values())
