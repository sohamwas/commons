"""Export a run as one self-contained JSON document.

This is the dashboard's only data contract, and it is deliberately the SAME shape whether
it comes from a live proxy over HTTP or from a file committed to the repo. That is what
lets the hosted demo run the identical React components with no backend at all
(handoff §15.3) — the determinism built for the A/B comparison pays for itself twice.

Organised BY CUSTOMER, not by agent. Every existing dashboard is organised by agent;
Commons is organised by the person being acted upon, and the data shape has to embody
that or the UI will drift back to an agent-centric list view (handoff §13).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from commons.proxy.registry import AGENTS
from commons.rules.engine import RuleEngine


def _json(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return raw


def export_run(db_path: str | Path, run_id: str | None = None) -> dict:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    if run_id is None:
        # The OPEN run: the one the gateway is currently writing to. The dashboard has to
        # show what the merchant's agents are doing right now, so this must agree with
        # Ledger.resume_or_start_run or the two disagree about what "the run" is.
        #
        # It used to pick the most recent run with any activity, a workaround for the
        # proxy opening an empty run on every boot. That is fixed at the source now, and
        # the workaround had become a bug: it showed a closed experiment in preference to
        # live traffic.
        row = conn.execute(
            "SELECT id FROM run WHERE ended_at IS NULL ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        if row is None:
            # No open run: reading a database from a finished simulation.
            row = conn.execute(
                """SELECT r.id FROM run r
                   WHERE EXISTS (SELECT 1 FROM call c WHERE c.run_id = r.id)
                   ORDER BY r.started_at DESC LIMIT 1"""
            ).fetchone()
        if row is None:
            conn.close()
            raise ValueError(f"no runs with activity in {db_path}")
        run_id = row["id"]

    run = dict(conn.execute("SELECT * FROM run WHERE id = ?", (run_id,)).fetchone())

    # ---- rule firings, grouped by call ----
    firings: dict[int, list[dict]] = {}
    for r in conn.execute(
        """SELECT rf.* FROM rule_fired rf JOIN call c ON c.id = rf.call_id
           WHERE c.run_id = ? ORDER BY rf.id""",
        (run_id,),
    ):
        firings.setdefault(r["call_id"], []).append(
            {
                "rule_id": r["rule_id"],
                "verdict": r["verdict"],
                "reason": r["reason"],
                "observed": r["observed"],
                "limit": r["limit_value"],
                "detail": _json(r["detail_json"]),
            }
        )

    # ---- the merchant's verdicts on what Commons flagged ----
    reviews: dict[int, list[dict]] = {}
    for r in conn.execute(
        """SELECT dr.* FROM decision_review dr JOIN call c ON c.id = dr.call_id
           WHERE c.run_id = ?""",
        (run_id,),
    ):
        reviews.setdefault(r["call_id"], []).append(
            {
                "rule_id": r["rule_id"],
                "verdict": r["verdict"],
                "note": r["note"],
                "reviewed_at": r["reviewed_at"],
            }
        )

    # ---- calls ----
    calls: list[dict] = []
    for r in conn.execute(
        "SELECT * FROM call WHERE run_id = ? ORDER BY sim_ts, id", (run_id,)
    ):
        fired = firings.get(r["id"], [])
        calls.append(
            {
                "id": r["id"],
                "ts": r["ts"],
                "sim_ts": r["sim_ts"],
                "agent_id": r["agent_id"],
                "upstream": r["upstream"],
                "tool": r["tool"],
                "action_class": r["action_class"],
                "entity_id": r["entity_id"],
                "entity_ref": r["entity_ref"],
                "magnitude": r["magnitude"],
                "magnitude_unit": r["magnitude_unit"],
                "resource": r["resource"],
                "decision": r["decision"],
                "forwarded": bool(r["forwarded"]),
                "is_error": bool(r["is_error"]),
                "latency_ms": r["latency_ms"],
                "args": _json(r["args_json"]),
                "result": _json(r["result_json"]),
                "rules_fired": fired,
                "violations": [f for f in fired if f["verdict"] != "ALLOW"],
                "reviews": reviews.get(r["id"], []),
                # A discount that does not say WHAT it discounts cannot be recognised as
                # a re-offer on something already discounted, so it is counted as a
                # separate giveaway and inflates the total. Surface it on the call
                # itself — an aggregate footnote is not enough for someone reading a
                # single customer's timeline and wondering why the maths looks high.
                "unattributed": (
                    r["action_class"] == "discount_grant"
                    and r["magnitude"] is not None
                    and r["resource"] is None
                ),
            }
        )

    # ---- entities, each carrying its own calls ----
    by_entity: dict[str, list[dict]] = {}
    for call in calls:
        if call["entity_id"]:
            by_entity.setdefault(call["entity_id"], []).append(call)

    entities: list[dict] = []
    for r in conn.execute("SELECT * FROM entity ORDER BY id"):
        # Quiet customers are included. Skipping everyone without activity in this run
        # is why a customer list imported on the Data page appeared to vanish: the
        # merchant had 12 new customers and the page showed none of them.
        entity_calls = by_entity.get(r["id"], [])

        handles = [
            [h["namespace"], h["value"]]
            for h in conn.execute(
                "SELECT namespace, value FROM identity WHERE entity_id = ? ORDER BY namespace",
                (r["id"],),
            )
        ]
        state = {
            s["key"]: s["value"]
            for s in conn.execute(
                "SELECT key, value FROM entity_state WHERE entity_id = ?", (r["id"],)
            )
        }

        agents_involved = sorted({c["agent_id"] for c in entity_calls})

        # Largest offer per resource, summed across resources — the SAME accounting the
        # CumulativeBudget rule uses. A naive sum here would show a customer 40% on the
        # timeline while the engine had enforced against 30%, and the dashboard would be
        # quietly contradicting the gateway.
        by_resource: dict[str, float] = {}
        for c in entity_calls:
            if c["action_class"] != "discount_grant" or not c["forwarded"]:
                continue
            if c["magnitude"] is None:
                continue
            # No resource means we cannot tell it apart from a re-offer, so it is kept
            # distinct — conservative, and flagged per call as `unattributed`.
            key = c["resource"] or f"call:{c['id']}"
            by_resource[key] = max(by_resource.get(key, 0.0), float(c["magnitude"]))
        discount = sum(by_resource.values())
        contacts = sum(
            1
            for c in entity_calls
            if c["action_class"] == "promotional_message" and c["forwarded"]
        )
        violations = sum(len(c["violations"]) for c in entity_calls)
        breaching_calls = sum(1 for c in entity_calls if c["violations"])
        unattributed = sum(1 for c in entity_calls if c.get("unattributed"))

        entities.append(
            {
                "id": r["id"],
                "display_name": r["display_name"],
                "handles": handles,
                "state": state,
                "agents": agents_involved,
                "call_ids": [c["id"] for c in entity_calls],
                "summary": {
                    "agent_count": len(agents_involved),
                    "calls": len(entity_calls),
                    "discount_pct": round(discount, 2),
                    "promotional_contacts": contacts,
                    "violations": violations,
                    # Rule breaches and the calls they happened on are different counts:
                    # one call can breach two rules at once. Showing only the first makes
                    # the timeline look like it is hiding rows.
                    "breaching_calls": breaching_calls,
                    "unattributed_grants": unattributed,
                },
            }
        )

    # Most-contested customers first — the dashboard is organised by exposure.
    entities.sort(
        key=lambda e: (
            e["summary"]["agent_count"],
            e["summary"]["violations"],
            e["summary"]["calls"],
        ),
        reverse=True,
    )

    # Reviews span runs — a merchant's judgement of a rule does not expire when a run
    # ends — so accuracy is counted across all of them.
    accuracy: dict[str, dict[str, int]] = {}
    for r in conn.execute(
        "SELECT rule_id, verdict, COUNT(*) n FROM decision_review GROUP BY rule_id, verdict"
    ):
        accuracy.setdefault(r["rule_id"], {})[r["verdict"]] = r["n"]

    engine = RuleEngine.load()
    rules = [
        {
            "id": rule.id,
            "english": rule.english,
            "primitive": type(rule).__name__,
            "on_violation": rule.on_violation,
            "scope": rule.scope,
            "fired": sum(
                1 for c in calls for f in c["rules_fired"] if f["rule_id"] == rule.id
            ),
            "violations": sum(
                1 for c in calls for f in c["violations"] if f["rule_id"] == rule.id
            ),
            "enabled": getattr(rule, "enabled", True),
            # How often the merchant agreed with this rule. A rule repeatedly marked
            # wrong is a rule that needs changing, and that is a far stronger signal
            # than asking anyone to read reason strings.
            "review": accuracy.get(rule.id, {}),
        }
        for rule in engine.rules
    ]

    conn.close()

    forwarded = sum(1 for c in calls if c["forwarded"])
    return {
        "run": run,
        "agents": [
            {"id": a.id, "display_name": a.display_name} for a in AGENTS.values()
        ],
        "rules": rules,
        "entities": entities,
        "calls": calls,
        "stats": {
            "calls": len(calls),
            "forwarded": forwarded,
            "stopped": len(calls) - forwarded,
            "entities": len(entities),
            # Customers an agent actually touched this run, as opposed to everyone the
            # merchant has ever imported.
            "active_entities": sum(1 for e in entities if e["summary"]["calls"]),
            "multi_agent_entities": sum(
                1 for e in entities if e["summary"]["agent_count"] > 1
            ),
            "violations": sum(len(c["violations"]) for c in calls),
            "total_discount_pct": round(
                sum(
                    c["magnitude"] or 0
                    for c in calls
                    if c["action_class"] == "discount_grant" and c["forwarded"]
                ),
                2,
            ),
        },
    }


def write_export(db_path: str | Path, out_path: str | Path, run_id: str | None = None) -> dict:
    data = export_run(db_path, run_id)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return data
