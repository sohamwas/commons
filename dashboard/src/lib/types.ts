export type Verdict = "ALLOW" | "DEFER" | "BLOCK";

export interface RuleFiring {
  rule_id: string;
  verdict: Verdict;
  reason: string;
  observed: number | null;
  limit: number | null;
  detail: Record<string, unknown> | null;
}

export interface Call {
  id: number;
  ts: string;
  sim_ts: string;
  agent_id: string;
  upstream: string;
  tool: string;
  action_class: string | null;
  entity_id: string | null;
  entity_ref: string | null;
  magnitude: number | null;
  magnitude_unit: string | null;
  resource: string | null;
  decision: Verdict;
  forwarded: boolean;
  is_error: boolean;
  latency_ms: number | null;
  args: Record<string, unknown> | null;
  result: unknown;
  rules_fired: RuleFiring[];
  violations: RuleFiring[];
  unattributed?: boolean;
  /** The merchant's verdicts on this call, one per rule that fired. */
  reviews?: CallReview[];
}

export interface CallReview {
  rule_id: string;
  verdict: "correct" | "incorrect" | "unsure";
  note: string | null;
  reviewed_at: string;
}

export interface EntitySummary {
  agent_count: number;
  calls: number;
  discount_pct: number;
  promotional_contacts: number;
  violations: number;
  breaching_calls: number;
  unattributed_grants: number;
}

/** Where a piece of state came from. A dispute_status can stop a payment, so the
 *  merchant has to be able to ask which dispute and get an answer. A null source is
 *  shown as an undocumented assertion rather than passed off as evidence. */
export interface StateProvenance {
  value: string | null;
  source: string | null;
  note: string | null;
  updated_at: string;
}

export interface Entity {
  id: string;
  display_name: string;
  handles: [string, string][];
  state: Record<string, string>;
  state_detail?: Record<string, StateProvenance>;
  agents: string[];
  call_ids: number[];
  summary: EntitySummary;
}

export interface Rule {
  id: string;
  english: string;
  primitive: string;
  on_violation: Verdict;
  scope: Record<string, unknown>;
  fired: number;
  violations: number;
}

export interface Agent {
  id: string;
  display_name: string;
}

export interface RunMeta {
  id: string;
  seed: number | null;
  mode: "OBSERVE" | "ENFORCE";
  started_at: string;
  ended_at: string | null;
  notes: string | null;
}

export interface RunData {
  run: RunMeta;
  agents: Agent[];
  rules: Rule[];
  entities: Entity[];
  calls: Call[];
  stats: {
    calls: number;
    forwarded: number;
    stopped: number;
    entities: number;
    /** Customers an agent touched this run, as opposed to everyone imported. */
    active_entities: number;
    multi_agent_entities: number;
    violations: number;
    total_discount_pct: number;
  };
}
