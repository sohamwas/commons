-- Commons decision ledger.
--
-- The proxy is the only writer. Every tool call from every agent lands here with the
-- entity it acted upon, so that rules can ask "has too much happened to this object?"
-- (handoff §6.2) — a question no per-agent permission system can answer.
--
-- Full args and results are stored because handoff §17.4 promises every violation ships
-- with a replayable trace. That cannot be reconstructed after the fact.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS run (
    id          TEXT PRIMARY KEY,
    seed        INTEGER,
    mode        TEXT NOT NULL CHECK (mode IN ('OBSERVE', 'ENFORCE')),
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    notes       TEXT
);

-- A canonical human. Identities from different vendors fold onto one of these.
CREATE TABLE IF NOT EXISTS entity (
    id           TEXT PRIMARY KEY,
    display_name TEXT,
    created_at   TEXT NOT NULL
);

-- The identity graph. DECLARATIVE, not inferred (handoff §11, plan D4).
-- (namespace, value) is the vendor-visible handle; entity_id is who it really is.
CREATE TABLE IF NOT EXISTS identity (
    namespace  TEXT NOT NULL,          -- phone | email | customer_id | order_id
    value      TEXT NOT NULL,          -- normalised (E.164 phone, lowercased email)
    entity_id  TEXT NOT NULL REFERENCES entity(id),
    source     TEXT,                   -- where this mapping came from
    PRIMARY KEY (namespace, value)
);
CREATE INDEX IF NOT EXISTS idx_identity_entity ON identity(entity_id);

-- Mutable per-entity state the rules read (e.g. dispute_status = 'open').
CREATE TABLE IF NOT EXISTS entity_state (
    entity_id  TEXT NOT NULL REFERENCES entity(id),
    key        TEXT NOT NULL,
    value      TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (entity_id, key)
);

-- Every tool call the proxy saw.
CREATE TABLE IF NOT EXISTS call (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL REFERENCES run(id),
    ts              TEXT NOT NULL,      -- wall clock
    sim_ts          TEXT,               -- simulated clock (Day 4)
    agent_id        TEXT NOT NULL,
    upstream        TEXT NOT NULL,
    tool            TEXT NOT NULL,
    action_class    TEXT,
    entity_id       TEXT REFERENCES entity(id),
    entity_ref      TEXT,               -- the raw handle as the agent supplied it
    magnitude       REAL,
    magnitude_unit  TEXT,
    resource        TEXT,               -- e.g. order_id, for mutual exclusion
    decision        TEXT NOT NULL DEFAULT 'ALLOW'
                    CHECK (decision IN ('ALLOW', 'DEFER', 'BLOCK')),
    forwarded       INTEGER NOT NULL DEFAULT 0,   -- did it actually reach the upstream?
    args_json       TEXT,
    result_json     TEXT,
    is_error        INTEGER NOT NULL DEFAULT 0,
    -- Malformed tool calls live in their own bucket so weak-model noise never
    -- contaminates the violation count (handoff §16.7).
    malformed       INTEGER NOT NULL DEFAULT 0,
    latency_ms      INTEGER
);
CREATE INDEX IF NOT EXISTS idx_call_entity ON call(entity_id, ts);
CREATE INDEX IF NOT EXISTS idx_call_run    ON call(run_id, ts);
CREATE INDEX IF NOT EXISTS idx_call_action ON call(entity_id, action_class, ts);

-- Every rule that fired on a call. All rules are evaluated, not just the first —
-- the hero UI's violation count depends on it (plan §4, engine contract).
CREATE TABLE IF NOT EXISTS rule_fired (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id     INTEGER NOT NULL REFERENCES call(id),
    rule_id     TEXT NOT NULL,
    verdict     TEXT NOT NULL CHECK (verdict IN ('ALLOW', 'DEFER', 'BLOCK')),
    reason      TEXT,
    observed    REAL,      -- what the ledger actually saw (e.g. 23.0 percent)
    limit_value REAL,      -- what the rule permits (e.g. 15.0)
    detail_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_rule_fired_call ON rule_fired(call_id);

-- The merchant's verdict on a decision Commons made.
--
-- This is what connects OBSERVE to ENFORCE. Without it they are two modes sharing an
-- engine but not a memory: the dry run tells you what WOULD have been stopped, and
-- nothing carries your judgement of it forward.
--
-- Keyed per (call, rule) rather than per call, because a single call can breach two
-- rules and a merchant may well agree with one and dispute the other.
CREATE TABLE IF NOT EXISTS decision_review (
    call_id     INTEGER NOT NULL REFERENCES call(id),
    rule_id     TEXT NOT NULL,
    verdict     TEXT NOT NULL CHECK (verdict IN ('correct', 'incorrect', 'unsure')),
    note        TEXT,
    reviewed_at TEXT NOT NULL,
    PRIMARY KEY (call_id, rule_id)
);
CREATE INDEX IF NOT EXISTS idx_review_rule ON decision_review(rule_id, verdict);
