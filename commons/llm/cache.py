"""Deterministic response cache.

Keyed on (role, model, exact prompt). If the same agent is asked the same question in
the same state, it replays the answer it already gave.

This is NOT cheating, and the README says so (handoff §16.4): the model genuinely made
that decision once for that exact context, and replaying it for an identical context is
what determinism means. It is also what makes the free tiers survive repeated runs, and
what makes dashboard iteration cost nothing.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_CACHE = Path("llm_cache.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_cache (
    key        TEXT PRIMARY KEY,
    role       TEXT,
    model      TEXT,
    response   TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS llm_usage (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    role          TEXT,
    model         TEXT,
    prompt_tokens INTEGER,
    output_tokens INTEGER,
    cached        INTEGER,
    at            TEXT
);
"""


def cache_key(role: str, model: str, payload: dict) -> str:
    blob = json.dumps({"role": role, "model": model, "payload": payload}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


class LLMCache:
    def __init__(self, path: Path | str = DEFAULT_CACHE) -> None:
        self.path = Path(path)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> dict | None:
        row = self.conn.execute(
            "SELECT response FROM llm_cache WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            self.misses += 1
            return None
        self.hits += 1
        return json.loads(row["response"])

    def put(self, key: str, role: str, model: str, response: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO llm_cache (key, role, model, response, created_at) "
            "VALUES (?,?,?,?,?)",
            (key, role, model, json.dumps(response), datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()

    def record_usage(
        self, role: str, model: str, prompt_tokens: int, output_tokens: int, cached: bool
    ) -> None:
        self.conn.execute(
            "INSERT INTO llm_usage (role, model, prompt_tokens, output_tokens, cached, at) "
            "VALUES (?,?,?,?,?,?)",
            (
                role,
                model,
                prompt_tokens,
                output_tokens,
                1 if cached else 0,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.conn.commit()

    def stats(self) -> dict:
        row = self.conn.execute(
            """SELECT COUNT(*) AS calls,
                      COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                      COALESCE(SUM(output_tokens), 0) AS output_tokens,
                      COALESCE(SUM(cached), 0) AS cached
               FROM llm_usage"""
        ).fetchone()
        total = self.hits + self.misses
        return {
            "calls": row["calls"],
            "prompt_tokens": row["prompt_tokens"],
            "output_tokens": row["output_tokens"],
            "cache_hits": self.hits,
            "cache_misses": self.misses,
            "hit_rate": round(self.hits / total, 3) if total else 0.0,
        }

    def close(self) -> None:
        self.conn.close()
