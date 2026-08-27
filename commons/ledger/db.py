"""The decision ledger — SQLite, single writer (the proxy).

Everything the rule engine needs to answer "has too much happened to this entity?"
lives here. Reads are ordinary SQL over indexed columns, which is why the rule
primitives in §4 can be pure functions of (call, ledger).
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
DEFAULT_DB = Path("commons.db")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Ledger:
    def __init__(self, path: Path | str = DEFAULT_DB) -> None:
        self.path = Path(path)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.conn.commit()
        self._lock = asyncio.Lock()
        self.run_id: str | None = None

    # ---------------- runs ----------------

    def start_run(self, mode: str = "OBSERVE", seed: int | None = None, notes: str = "") -> str:
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        self.conn.execute(
            "INSERT INTO run (id, seed, mode, started_at, notes) VALUES (?,?,?,?,?)",
            (run_id, seed, mode, _now(), notes),
        )
        self.conn.commit()
        self.run_id = run_id
        return run_id

    def end_run(self, run_id: str | None = None) -> None:
        self.conn.execute(
            "UPDATE run SET ended_at = ? WHERE id = ?", (_now(), run_id or self.run_id)
        )
        self.conn.commit()

    # ---------------- entities & identity ----------------

    def entity_for(self, namespace: str, value: str, source: str = "") -> str:
        """Resolve a vendor-visible handle to a canonical entity, creating it if new."""
        row = self.conn.execute(
            "SELECT entity_id FROM identity WHERE namespace = ? AND value = ?",
            (namespace, value),
        ).fetchone()
        if row:
            return row["entity_id"]

        entity_id = f"ent_{uuid.uuid4().hex[:10]}"
        self.conn.execute(
            "INSERT INTO entity (id, display_name, created_at) VALUES (?,?,?)",
            (entity_id, f"{namespace}:{value}", _now()),
        )
        self.conn.execute(
            "INSERT INTO identity (namespace, value, entity_id, source) VALUES (?,?,?,?)",
            (namespace, value, entity_id, source),
        )
        self.conn.commit()
        return entity_id

    def lookup_identity(self, namespace: str, value: str) -> str | None:
        """Resolve a handle WITHOUT creating anything. Used when deciding whether a
        vendor-asserted link is new, redundant, or in conflict with what we already know."""
        row = self.conn.execute(
            "SELECT entity_id FROM identity WHERE namespace = ? AND value = ?",
            (namespace, value),
        ).fetchone()
        return row["entity_id"] if row else None

    def link_identity(
        self, namespace: str, value: str, entity_id: str, source: str = "declared"
    ) -> None:
        """Declare that a handle belongs to a known entity.

        This is how the world simulator seeds the graph: one customer is declared to own
        a phone, an email and a Razorpay customer_id up front. Declarative, not inferred
        (handoff §11) — the merchant states the mapping once per server.
        """
        self.conn.execute(
            "INSERT OR REPLACE INTO identity (namespace, value, entity_id, source) VALUES (?,?,?,?)",
            (namespace, value, entity_id, source),
        )
        self.conn.commit()

    def create_entity(self, display_name: str) -> str:
        entity_id = f"ent_{uuid.uuid4().hex[:10]}"
        self.conn.execute(
            "INSERT INTO entity (id, display_name, created_at) VALUES (?,?,?)",
            (entity_id, display_name, _now()),
        )
        self.conn.commit()
        return entity_id

    def identities_of(self, entity_id: str) -> list[tuple[str, str]]:
        rows = self.conn.execute(
            "SELECT namespace, value FROM identity WHERE entity_id = ? ORDER BY namespace",
            (entity_id,),
        ).fetchall()
        return [(r["namespace"], r["value"]) for r in rows]

    # ---------------- entity state ----------------

    def set_state(self, entity_id: str, key: str, value: Any) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO entity_state (entity_id, key, value, updated_at) VALUES (?,?,?,?)",
            (entity_id, key, None if value is None else str(value), _now()),
        )
        self.conn.commit()

    def get_state(self, entity_id: str, key: str, default: Any = None) -> Any:
        row = self.conn.execute(
            "SELECT value FROM entity_state WHERE entity_id = ? AND key = ?", (entity_id, key)
        ).fetchone()
        return row["value"] if row else default

    def state_of(self, entity_id: str) -> dict[str, str]:
        rows = self.conn.execute(
            "SELECT key, value FROM entity_state WHERE entity_id = ?", (entity_id,)
        ).fetchall()
        return {r["key"]: r["value"] for r in rows}

    # ---------------- calls ----------------

    def record_call(self, **fields: Any) -> int:
        fields.setdefault("run_id", self.run_id)
        fields.setdefault("ts", _now())
        # Rules reason about SIMULATED time (a 30-day month compressed into a minute).
        # Outside a simulation the two clocks are the same, so defaulting here means
        # the engine never has to care which world it is running in.
        fields.setdefault("sim_ts", fields["ts"])
        for k in ("args_json", "result_json"):
            if k in fields and not isinstance(fields[k], (str, type(None))):
                fields[k] = json.dumps(fields[k], default=str)[:200_000]
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        cur = self.conn.execute(
            f"INSERT INTO call ({cols}) VALUES ({marks})", tuple(fields.values())
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_call(self, call_id: int, **fields: Any) -> None:
        if not fields:
            return
        for k in ("args_json", "result_json"):
            if k in fields and not isinstance(fields[k], (str, type(None))):
                fields[k] = json.dumps(fields[k], default=str)[:200_000]
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.conn.execute(
            f"UPDATE call SET {sets} WHERE id = ?", (*fields.values(), call_id)
        )
        self.conn.commit()

    def record_rule_fired(self, call_id: int, **fields: Any) -> None:
        fields["call_id"] = call_id
        if "detail_json" in fields and not isinstance(fields["detail_json"], (str, type(None))):
            fields["detail_json"] = json.dumps(fields["detail_json"], default=str)
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        self.conn.execute(f"INSERT INTO rule_fired ({cols}) VALUES ({marks})", tuple(fields.values()))
        self.conn.commit()

    # ---------------- merchant review: what connects OBSERVE to ENFORCE ----------------

    def record_review(
        self, call_id: int, rule_id: str, verdict: str, note: str = ""
    ) -> None:
        """Record the merchant's judgement of one rule firing on one call."""
        self.conn.execute(
            "INSERT OR REPLACE INTO decision_review "
            "(call_id, rule_id, verdict, note, reviewed_at) VALUES (?,?,?,?,?)",
            (call_id, rule_id, verdict, note, _now()),
        )
        self.conn.commit()

    def reviews_for_run(self, run_id: str | None = None) -> dict[int, list[dict]]:
        rows = self.conn.execute(
            """SELECT dr.* FROM decision_review dr
               JOIN call c ON c.id = dr.call_id WHERE c.run_id = ?""",
            (run_id or self.run_id,),
        ).fetchall()
        out: dict[int, list[dict]] = {}
        for r in rows:
            out.setdefault(r["call_id"], []).append(
                {
                    "rule_id": r["rule_id"],
                    "verdict": r["verdict"],
                    "note": r["note"],
                    "reviewed_at": r["reviewed_at"],
                }
            )
        return out

    def rule_accuracy(self) -> dict[str, dict[str, int]]:
        """Per rule: how often the merchant agreed with it.

        A rule the merchant keeps marking wrong is a rule that needs changing — that is a
        far stronger signal than asking them to read reason strings, and it is the whole
        point of running OBSERVE before ENFORCE.

        Reviews are counted across ALL runs, because a merchant's judgement of a rule does
        not expire when a run ends.
        """
        rows = self.conn.execute(
            "SELECT rule_id, verdict, COUNT(*) n FROM decision_review GROUP BY rule_id, verdict"
        ).fetchall()
        out: dict[str, dict[str, int]] = {}
        for r in rows:
            out.setdefault(r["rule_id"], {})[r["verdict"]] = r["n"]
        return out

    # ---------------- queries the rule engine needs ----------------

    # Only `forwarded = 1` rows count. In OBSERVE a violating call really happened, so it
    # consumes budget for everything after it; in ENFORCE it was stopped, so it does not.
    # That single condition is what makes the A/B comparison mean something.

    def count_actions(
        self, entity_id: str, action_classes: tuple[str, ...], since_iso: str, run_id: str | None = None
    ) -> int:
        marks = ", ".join("?" for _ in action_classes)
        row = self.conn.execute(
            f"""SELECT COUNT(*) AS n FROM call
                WHERE entity_id = ? AND run_id = ? AND forwarded = 1
                  AND action_class IN ({marks}) AND sim_ts >= ?""",
            (entity_id, run_id or self.run_id, *action_classes, since_iso),
        ).fetchone()
        return int(row["n"])

    def sum_magnitude(
        self, entity_id: str, action_classes: tuple[str, ...], since_iso: str, run_id: str | None = None
    ) -> float:
        marks = ", ".join("?" for _ in action_classes)
        row = self.conn.execute(
            f"""SELECT COALESCE(SUM(magnitude), 0) AS s FROM call
                WHERE entity_id = ? AND run_id = ? AND forwarded = 1
                  AND action_class IN ({marks}) AND sim_ts >= ?""",
            (entity_id, run_id or self.run_id, *action_classes, since_iso),
        ).fetchone()
        return float(row["s"])

    def sum_max_magnitude_per_resource(
        self,
        entity_id: str,
        action_classes: tuple[str, ...],
        since_iso: str,
        exclude_resource: str | None = None,
        run_id: str | None = None,
    ) -> float:
        """Largest magnitude per resource, summed across resources.

        What a customer can actually receive, rather than how many times it was offered.
        The resource the candidate call is about is EXCLUDED, because the candidate is
        a re-offer on it and will be compared against the cap itself — otherwise a repeat
        offer would be counted twice. Calls with no resource are each treated as distinct,
        since nothing says they are the same thing.
        """
        marks = ", ".join("?" for _ in action_classes)
        rows = self.conn.execute(
            f"""SELECT resource, MAX(magnitude) AS m, COUNT(*) AS n FROM call
                WHERE entity_id = ? AND run_id = ? AND forwarded = 1
                  AND action_class IN ({marks}) AND sim_ts >= ?
                  AND magnitude IS NOT NULL
                GROUP BY COALESCE(resource, 'call:' || id)""",
            (entity_id, run_id or self.run_id, *action_classes, since_iso),
        ).fetchall()
        total = 0.0
        unattributed = 0
        for row in rows:
            if exclude_resource is not None and row["resource"] == exclude_resource:
                continue
            total += float(row["m"] or 0)
            if row["resource"] is None:
                unattributed += 1
        # The count travels with the total so a rule can say whether a breach might be an
        # attribution artefact rather than a real one. Failing closed is right, but a
        # merchant reading "you are over your cap" deserves to know when part of that sum
        # is offers we could not tell apart.
        self.last_unattributed_contributors = unattributed
        return total

    def last_actor_on_resource(
        self, resource: str, since_iso: str, run_id: str | None = None
    ) -> tuple[str, str] | None:
        """Who last touched this resource, and when. Used for mutual exclusion."""
        row = self.conn.execute(
            """SELECT agent_id, sim_ts FROM call
               WHERE resource = ? AND run_id = ? AND forwarded = 1 AND sim_ts >= ?
               ORDER BY sim_ts DESC LIMIT 1""",
            (resource, run_id or self.run_id, since_iso),
        ).fetchone()
        return (row["agent_id"], row["sim_ts"]) if row else None

    def last_action_of_class(
        self, entity_id: str, action_class: str, since_iso: str, run_id: str | None = None
    ) -> tuple[str, str] | None:
        """Most recent agent to apply this action class to this entity, and when."""
        row = self.conn.execute(
            """SELECT agent_id, sim_ts FROM call
               WHERE entity_id = ? AND run_id = ? AND forwarded = 1
                 AND action_class = ? AND sim_ts >= ?
               ORDER BY sim_ts DESC LIMIT 1""",
            (entity_id, run_id or self.run_id, action_class, since_iso),
        ).fetchone()
        return (row["agent_id"], row["sim_ts"]) if row else None

    def calls_for_entity(self, entity_id: str, run_id: str | None = None) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM call WHERE entity_id = ? AND run_id = ? ORDER BY ts",
            (entity_id, run_id or self.run_id),
        ).fetchall()

    def close(self) -> None:
        self.conn.close()
