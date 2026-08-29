"""Merge customer records that an earlier import split in two.

    .venv/Scripts/python.exe scripts/repair_entities.py --db observe.db          # report
    .venv/Scripts/python.exe scripts/repair_entities.py --db observe.db --apply  # merge

Before commit 4ea7304 the importer created a new entity for every row on every import and
repointed that row's handles onto it with INSERT OR REPLACE. The original was left behind
holding the call history but no handles: the same person as two records, one you can find
and one that has everything.

That fix stops new damage. This repairs a database that already took it.

MATCHING IS BY EXACT display_name, which is the only link left once the handles have
moved. That is safe for the damage described above and NOT safe in general, because two
different customers can share a name. It is dry-run by default and prints every merge, so
read the report before passing --apply.
"""

from __future__ import annotations

import argparse
import sqlite3
from collections import defaultdict


def load(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT e.id, e.display_name, e.created_at,
                  (SELECT COUNT(*) FROM identity i WHERE i.entity_id = e.id) handles,
                  (SELECT COUNT(*) FROM call c WHERE c.entity_id = e.id)     calls
           FROM entity e ORDER BY e.created_at"""
    ).fetchall()


def merge(conn: sqlite3.Connection, keep: str, drop: str) -> None:
    """Move everything from `drop` onto `keep`, then remove `drop`.

    Handles use INSERT OR REPLACE so a handle already on `keep` wins; entity_state the
    same. Neither can conflict in practice here, since the two records are the same
    person split in half.
    """
    conn.execute("UPDATE call SET entity_id = ? WHERE entity_id = ?", (keep, drop))
    conn.execute(
        "UPDATE OR REPLACE identity SET entity_id = ? WHERE entity_id = ?", (keep, drop)
    )
    conn.execute(
        "UPDATE OR REPLACE entity_state SET entity_id = ? WHERE entity_id = ?", (keep, drop)
    )
    conn.execute("DELETE FROM identity WHERE entity_id = ?", (drop,))
    conn.execute("DELETE FROM entity_state WHERE entity_id = ?", (drop,))
    conn.execute("DELETE FROM entity WHERE id = ?", (drop,))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="observe.db")
    parser.add_argument("--apply", action="store_true", help="write the merges")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    rows = load(conn)
    by_name: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        by_name[row["display_name"]].append(row)

    merges: list[tuple[sqlite3.Row, list[sqlite3.Row]]] = []
    for name, group in by_name.items():
        if len(group) < 2:
            continue
        # Keep the oldest: it holds the original history, and its id is what anything
        # else already recorded points at.
        keep, *rest = sorted(group, key=lambda r: r["created_at"])
        merges.append((keep, rest))

    if not merges:
        print(f"{len(rows)} entities, nothing to merge")
        return 0

    print(f"{len(rows)} entities, {len(merges)} split across duplicates\n")
    for keep, rest in merges:
        print(f"  {keep['display_name']}")
        print(f"    keep  {keep['id']}  handles={keep['handles']} calls={keep['calls']}")
        for row in rest:
            print(f"    merge {row['id']}  handles={row['handles']} calls={row['calls']}")

    removed = sum(len(rest) for _, rest in merges)
    if not args.apply:
        print(f"\nwould remove {removed} duplicate records. Re-run with --apply to do it.")
        return 0

    for keep, rest in merges:
        for row in rest:
            merge(conn, keep["id"], row["id"])
    conn.commit()

    after = load(conn)
    orphans = [r for r in after if r["handles"] == 0 and r["calls"] == 0]
    for row in orphans:
        conn.execute("DELETE FROM entity WHERE id = ?", (row["id"],))
    conn.commit()

    print(f"\nmerged {removed} duplicates, removed {len(orphans)} empty records")
    print(f"{len(after) - len(orphans)} customers remain")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
