"""Merchant-editable settings, held in one mutable place.

Mode and policy were baked in at startup — a CLI flag and a YAML file read once. That is
fine for a demo and wrong for a tool: a merchant running Commons on their own machine has
to be able to change the discount cap to 10%, switch a rule from BLOCK to DEFER, or flip
to ENFORCE, without editing files and restarting the gateway their agents are talking to.

Everything here is read at DECISION TIME rather than captured at build time, so a change
takes effect on the very next tool call.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from commons.rules.engine import OBSERVE, RULESET_PATH, RuleEngine

logger = logging.getLogger(__name__)


@dataclass
class Settings:
    """Live configuration. Mutated in place so open MCP sessions see changes."""

    mode: str = OBSERVE
    engine: RuleEngine = field(default_factory=RuleEngine.load)
    ruleset_path: Path = RULESET_PATH

    # ---------------- mode ----------------

    def set_mode(self, mode: str) -> str:
        if mode not in ("OBSERVE", "ENFORCE"):
            raise ValueError(f"unknown mode: {mode}")
        self.mode = mode
        logger.warning("mode changed to %s", mode)
        return self.mode

    # ---------------- policy ----------------

    def ruleset_dict(self) -> list[dict]:
        return yaml.safe_load(self.ruleset_path.read_text(encoding="utf-8")) or []

    @staticmethod
    def english_disagrees(rule) -> str | None:
        """Does the merchant's sentence still match the number being enforced?

        Handoff §9 promises the plain-English rule is shown beside the compiled invariant
        so a merchant can check that what was written is what is enforced. Editing a
        threshold through the UI breaks that quietly: change the cap to 10% and the
        sentence still reads "more than 15%", so the screen now states one number while
        the gateway enforces another. Detect it and say so rather than let the two drift.
        """
        import re

        # Every number the rule actually enforces, including the ones inside durations
        # like "24h" or "30d".
        enforced: set[str] = set()
        for key in ("cap", "max", "window", "lease"):
            value = rule.scope.get(key)
            if value is not None:
                enforced.update(re.findall(r"\d+", str(value)))
        if not enforced:
            return None

        quoted = set(re.findall(r"\d+", rule.english))
        # The test is whether every number in the sentence is accounted for — NOT whether
        # any of them match. "no more than 15% in any 30-day period" against a cap of 10
        # shares the 30 and would pass an intersection test while still lying about the
        # number that matters.
        orphans = quoted - enforced
        if orphans:
            return (
                f"the sentence says {sorted(orphans)} but this rule enforces "
                f"{sorted(enforced)}"
            )
        return None

    def policy(self) -> dict:
        """Everything a merchant can change, in one payload."""
        return {
            "mode": self.mode,
            "rules": [
                {
                    "id": r.id,
                    "english": r.english,
                    "primitive": type(r).__name__,
                    "on_violation": r.on_violation,
                    "scope": r.scope,
                    "enabled": getattr(r, "enabled", True),
                    "compiled": r.compiled,
                    "english_mismatch": self.english_disagrees(r),
                }
                for r in self.engine.rules
            ],
        }

    def update_rules(self, updates: list[dict]) -> dict:
        """Apply merchant edits and reload the engine.

        Writes back to `ruleset.yaml` so the change survives a restart, then rebuilds the
        engine in place. Anything not mentioned in an update keeps its current value —
        a merchant changing a cap should not have to resend the whole rule.
        """
        current = {r["id"]: r for r in self.ruleset_dict()}

        for update in updates:
            rule_id = update.get("id")
            if rule_id not in current:
                raise ValueError(f"unknown rule: {rule_id}")
            rule = current[rule_id]

            if "english" in update:
                rule["english"] = update["english"]
            if "on_violation" in update:
                if update["on_violation"] not in ("BLOCK", "DEFER"):
                    raise ValueError("on_violation must be BLOCK or DEFER")
                rule["on_violation"] = update["on_violation"]
            if "enabled" in update:
                rule["enabled"] = bool(update["enabled"])
            for key, value in (update.get("scope") or {}).items():
                rule.setdefault("scope", {})[key] = value

        ordered = [current[r["id"]] for r in self.ruleset_dict()]
        self.ruleset_path.write_text(
            yaml.safe_dump(ordered, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
        self.engine = RuleEngine.load(self.ruleset_path)
        logger.warning("policy updated: %s", [u.get("id") for u in updates])
        return self.policy()
