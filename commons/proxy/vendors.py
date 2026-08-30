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

# env:NAME anywhere in a header value, so "Bearer env:TOKEN" composes.
ENV_REF = re.compile(r"env:([A-Za-z_][A-Za-z0-9_]*)")


class InvalidVendor(ValueError):
    """The submitted vendor cannot be registered, with a reason a merchant can act on."""


@dataclass
class VendorDef:
    """One MCP server, reached either over HTTP or by running a local command.

    Both matter. Hosted vendors speak streamable HTTP, and a great many MCP servers ship
    as something you run (`npx -y some-server`), which is how most of the ecosystem is
    distributed. Supporting only URLs would have left most of it unreachable.
    """

    name: str
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    command: str = ""
    args: list[str] = field(default_factory=list)
    # Set for vendors Commons knows how to authenticate itself, so the merchant does not
    # have to hand-build a header from keys that are already in .env.
    auth: str | None = None

    def as_dict(self) -> dict:
        body: dict = {}
        if self.command:
            body["command"] = self.command
            if self.args:
                body["args"] = list(self.args)
        else:
            body["url"] = self.url
        if self.headers:
            body["headers"] = dict(self.headers)
        if self.auth:
            body["auth"] = self.auth
        return body

    def _resolve(self, value: str) -> str:
        """Substitute every env:NAME in the value, wherever it appears.

        Resolving only a value that STARTS with env: made the common case impossible.
        Almost every hosted MCP server wants `Authorization: Bearer <token>`, and neither
        spelling worked: "env:TOKEN" produced a bare token with no scheme, and
        "Bearer env:TOKEN" did not start with the prefix so it was sent literally. Both
        came back Unauthorized, which is a confusing way to learn that the placeholder
        cannot be composed with anything.
        """

        def swap(match: re.Match) -> str:
            env_name = match.group(1)
            found = os.environ.get(env_name, "").strip()
            if not found:
                raise InvalidVendor(
                    f"'{self.name}' expects a value from ${env_name}, "
                    "which is not set in .env"
                )
            return found

        return ENV_REF.sub(swap, value)

    def to_upstream(self) -> UpstreamConfig:
        if self.auth == "razorpay":
            try:
                return razorpay_remote()
            except RuntimeError as exc:
                # config.py signals a missing key, or a live key where a test key is
                # required, with RuntimeError. upstream_configs() below turns a bad
                # vendor into one reported as unavailable rather than a dead gateway,
                # but it can only do that for InvalidVendor: a RuntimeError went
                # straight past it and took the process down at boot.
                #
                # That is how a copied .env.example killed a first run. The file set
                # RAZORPAY_KEY_ID to a placeholder and left the secret empty, which was
                # enough to look configured and not enough to authenticate.
                raise InvalidVendor(f"'{self.name}' cannot authenticate: {exc}") from exc
        if self.command:
            return UpstreamConfig(
                name=self.name,
                kind="stdio",
                command=self.command,
                args=list(self.args),
                env={k: self._resolve(v) for k, v in self.headers.items()},
            )
        return UpstreamConfig(
            name=self.name,
            kind="http",
            url=self.url,
            headers={k: self._resolve(v) for k, v in self.headers.items()},
        )


def parse_vendor(name: str, raw: dict) -> VendorDef:
    if not isinstance(name, str) or not NAME_PATTERN.match(name):
        raise InvalidVendor(
            f"'{name}' is not a usable vendor name. Use lowercase letters, digits and "
            "hyphens, starting with a letter or digit."
        )
    body = raw or {}
    auth = body.get("auth")
    url = str(body.get("url") or "").strip()
    command = str(body.get("command") or "").strip()

    if auth == "razorpay":
        return VendorDef(name=name, url=url or "https://mcp.razorpay.com/mcp", auth=auth)

    headers = body.get("headers") or {}
    if not isinstance(headers, dict):
        raise InvalidVendor(f"'{name}' has headers that are not a mapping.")
    headers = {str(k): str(v) for k, v in headers.items()}

    if command:
        args = body.get("args") or []
        if isinstance(args, str):
            args = args.split()
        if not isinstance(args, (list, tuple)):
            raise InvalidVendor(f"'{name}' has args that are not a list.")
        return VendorDef(
            name=name, command=command, args=[str(a) for a in args], headers=headers
        )

    if not url.startswith(("http://", "https://")):
        raise InvalidVendor(
            f"'{name}' needs either an http/https MCP URL or a command to run."
        )

    return VendorDef(name=name, url=url, headers=headers)


def seed_defaults() -> dict[str, VendorDef]:
    """What a first run starts with.

    Razorpay only if its keys are present, because an entry that cannot authenticate is
    worse than no entry: the gateway starts, reports a vendor as unavailable, and the
    merchant has to work out that the cause is an empty .env.
    """
    vendors: dict[str, VendorDef] = {}
    # BOTH halves, not just the id. A key id on its own cannot authenticate, and checking
    # only the id let a placeholder .env add a vendor that could never work.
    if (
        os.environ.get("RAZORPAY_KEY_ID", "").strip()
        and os.environ.get("RAZORPAY_KEY_SECRET", "").strip()
    ):
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
