"""The Tool Semantics Manifest (plan §3).

A rule like "max 15% total discount per customer per 30 days" needs three things from a
tool call Commons has never seen before:

    1. which entity is being acted upon
    2. what class of action this is
    3. what magnitude it consumes

Least-privilege systems need none of these — they only ask "may this actor call this
tool?" — which is precisely why they cannot express the rules in handoff §6.3.

Everything here is DECLARED from a tool's public schema, never inferred from its source.
That is what lets Commons govern a third-party agent you cannot inspect: you need the
vendor's tool schema, which is public by construction, and nothing else.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

MANIFEST_DIR = Path(__file__).with_name("manifests")

# Action classes. Rules are written against these, not against tool names, so a rule
# survives a vendor renaming a tool or a second vendor arriving with its own.
READ = "read"
PROMOTIONAL_MESSAGE = "promotional_message"
TRANSACTIONAL_MESSAGE = "transactional_message"
DISCOUNT_GRANT = "discount_grant"
REFUND = "refund"
DISPUTE_ACTION = "dispute_action"
FULFILMENT_RESTRICTION = "fulfilment_restriction"


@dataclass(frozen=True)
class Extractor:
    source: str  # "args" | "upstream_lookup"
    path: str
    namespace: str | None = None          # identity namespace, for entity extractors
    lookup_tool: str | None = None        # for source == "upstream_lookup"
    lookup_args: dict[str, str] = field(default_factory=dict)  # upstream param -> path in caller args


@dataclass(frozen=True)
class Override:
    """Conditionally reclassify an action, e.g. transactional vs promotional.

    Whatever an override reads should be merchant-declared, not caller-declared. A field
    the calling agent controls must not decide whether policy applies to it.
    """

    path: str
    then: str
    equals: str | None = None
    one_of: tuple[str, ...] = ()

    def matches(self, value: object) -> bool:
        if value is None:
            return False
        text = str(value)
        if self.one_of:
            return text in self.one_of
        return text == self.equals


@dataclass(frozen=True)
class ToolSemantics:
    tool: str
    action_class: str
    entity: Extractor | None = None
    magnitude: Extractor | None = None
    magnitude_unit: str | None = None
    resource: Extractor | None = None
    overrides: tuple[Override, ...] = ()
    # Other handles for the SAME customer carried in this one call. The vendor is
    # asserting they belong together, so recording the link is not inference.
    also_identifies: tuple[Extractor, ...] = ()

    @property
    def governed(self) -> bool:
        """Reads are logged but never blocked — they consume nothing shared."""
        return self.action_class != READ


@dataclass(frozen=True)
class Manifest:
    upstream: str
    tools: dict[str, ToolSemantics]

    def get(self, tool: str) -> ToolSemantics | None:
        return self.tools.get(tool)


def _extractor(raw: dict[str, Any] | None) -> Extractor | None:
    if not raw:
        return None
    return Extractor(
        source=raw.get("from", "args"),
        path=raw.get("path", ""),
        namespace=raw.get("as"),
        lookup_tool=raw.get("tool"),
        lookup_args=dict(raw.get("args") or {}),
    )


def load_manifest(path: Path) -> Manifest:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    tools: dict[str, ToolSemantics] = {}
    for name, spec in (data.get("tools") or {}).items():
        spec = spec or {}
        mag = _extractor(spec.get("magnitude"))
        tools[name] = ToolSemantics(
            tool=name,
            action_class=spec.get("action_class", READ),
            entity=_extractor(spec.get("entity")),
            magnitude=mag,
            magnitude_unit=(spec.get("magnitude") or {}).get("unit"),
            resource=_extractor(spec.get("resource")),
            overrides=tuple(
                Override(
                    path=o["if"]["path"],
                    then=o["then"],
                    equals=None if "equals" not in o["if"] else str(o["if"]["equals"]),
                    one_of=tuple(str(v) for v in (o["if"].get("in") or ())),
                )
                for o in (spec.get("action_class_when") or [])
            ),
            also_identifies=tuple(
                _extractor(x) for x in (spec.get("also_identifies") or []) if _extractor(x)
            ),
        )
    return Manifest(upstream=data["upstream"], tools=tools)


def load_manifests(directory: Path = MANIFEST_DIR) -> dict[str, Manifest]:
    manifests: dict[str, Manifest] = {}
    for path in sorted(directory.glob("*.yaml")):
        m = load_manifest(path)
        manifests[m.upstream] = m
        logger.info("manifest loaded: %s (%d tools)", m.upstream, len(m.tools))
    return manifests


# --------------------------------------------------------------------------------------
# extraction
# --------------------------------------------------------------------------------------


def dig(obj: Any, path: str | list[str]) -> Any:
    """Walk a dotted path. Tolerates JSON-encoded strings mid-path, which Razorpay's
    `notes` field routinely contains.

    A list of paths is tried in order and the first hit wins — a subscription retry and
    a cart both identify "the thing being discounted", but under different argument names.
    """
    if isinstance(path, list):
        for candidate in path:
            found = dig(obj, candidate)
            if found is not None:
                return found
        return None
    if not path:
        return None
    cur = obj
    for part in path.split("."):
        if isinstance(cur, str):
            try:
                cur = json.loads(cur)
            except (json.JSONDecodeError, ValueError):
                return None
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit():
            cur = cur[int(part)] if int(part) < len(cur) else None
        else:
            return None
        if cur is None:
            return None
    return cur


def to_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().rstrip("%").strip()
    try:
        return float(text)
    except ValueError:
        return None


def action_class_for(sem: ToolSemantics, args: dict) -> str:
    for override in sem.overrides:
        if override.matches(dig(args, override.path)):
            return override.then
    return sem.action_class


@dataclass
class CallFacts:
    """What the rule engine needs to know about one tool call."""

    action_class: str | None
    governed: bool
    entity_id: str | None = None
    entity_ref: str | None = None
    magnitude: float | None = None
    magnitude_unit: str | None = None
    resource: str | None = None
    # Extra handles this call taught us about, and any disagreements it surfaced.
    linked_handles: list[tuple[str, str]] = field(default_factory=list)
    identity_conflicts: list[tuple[str, str]] = field(default_factory=list)


async def _extract(
    ex: Extractor, args: dict, upstream, lookup_cache: dict[tuple, Any] | None
) -> Any:
    if ex.source == "args":
        return dig(args, ex.path)

    if ex.source == "upstream_lookup":
        if upstream is None or not ex.lookup_tool:
            return None
        call_args = {param: dig(args, src) for param, src in ex.lookup_args.items()}
        if any(v is None for v in call_args.values()):
            return None
        key = (upstream.name, ex.lookup_tool, tuple(sorted(call_args.items())))
        if lookup_cache is not None and key in lookup_cache:
            payload = lookup_cache[key]
        else:
            try:
                res = await upstream.call_tool(ex.lookup_tool, call_args)
            except Exception as exc:  # noqa: BLE001 — a lookup failure must not break the call
                logger.warning("entity lookup failed (%s): %s", ex.lookup_tool, exc)
                return None
            if res.is_error:
                return None
            text = "".join(c.text for c in res.content if getattr(c, "type", None) == "text")
            try:
                payload = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                return None
            if lookup_cache is not None:
                lookup_cache[key] = payload
        return dig(payload, ex.path)

    logger.warning("unknown extractor source: %s", ex.source)
    return None


async def derive_facts(
    sem: ToolSemantics,
    args: dict,
    resolver,
    upstream=None,
    lookup_cache: dict[tuple, Any] | None = None,
) -> CallFacts:
    """Turn a raw tool call into the facts a rule can be evaluated against."""
    facts = CallFacts(action_class=action_class_for(sem, args), governed=sem.governed)

    if sem.entity is not None:
        raw = await _extract(sem.entity, args, upstream, lookup_cache)
        entity_id, normalised = resolver.resolve(
            sem.entity.namespace or "customer_id", raw, source=f"{sem.tool}"
        )
        facts.entity_id = entity_id
        facts.entity_ref = normalised

        # Any other handles this same call carries belong to the same customer —
        # the vendor said so by putting them in one payload. Recording them means
        # identities knit together as traffic flows, instead of depending entirely
        # on the merchant seeding every mapping up front.
        if entity_id is not None:
            for extra in sem.also_identifies:
                extra_raw = await _extract(extra, args, upstream, lookup_cache)
                if extra_raw is None:
                    continue
                outcome = resolver.link_if_new(
                    entity_id,
                    extra.namespace or "customer_id",
                    extra_raw,
                    source=f"asserted-by:{sem.tool}",
                )
                if outcome == "linked":
                    facts.linked_handles.append((extra.namespace or "customer_id", str(extra_raw)))
                elif outcome == "conflict":
                    facts.identity_conflicts.append(
                        (extra.namespace or "customer_id", str(extra_raw))
                    )

    if sem.magnitude is not None:
        facts.magnitude = to_number(await _extract(sem.magnitude, args, upstream, lookup_cache))
        facts.magnitude_unit = sem.magnitude_unit

    if sem.resource is not None:
        raw = await _extract(sem.resource, args, upstream, lookup_cache)
        facts.resource = None if raw is None else str(raw)

    return facts
