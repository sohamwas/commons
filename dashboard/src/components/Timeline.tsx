"use client";

import type { Agent, Call, Entity } from "@/lib/types";
import { formatDay, formatTime, handleOf, maskPhone } from "@/lib/datasource";

/**
 * The hero screen.
 *
 * Every other agent dashboard in existence is organised BY AGENT — one lane, one agent,
 * one green tick. Commons is organised by the person being acted upon, so the lanes
 * converge instead of running in parallel, and the violations are drawn BETWEEN the
 * lanes, because that is literally where they live: in the space no single agent can see.
 */

const LANE_COLOR: Record<string, string> = {
  "cart-recovery": "var(--agent-cart)",
  "subscription-recovery": "var(--agent-subscription)",
  "dispute-responder": "var(--agent-dispute)",
  "rto-shield": "var(--agent-rto)",
};

interface Props {
  entity: Entity;
  calls: Call[];
  agents: Agent[];
  selectedCallId: number | null;
  onSelectCall: (id: number | null) => void;
}

export default function Timeline({
  entity,
  calls,
  agents,
  selectedCallId,
  onSelectCall,
}: Props) {
  if (calls.length === 0) {
    return <div className="empty">No activity recorded for this customer.</div>;
  }

  const times = calls.map((c) => new Date(c.sim_ts).getTime());
  const min = Math.min(...times);
  const max = Math.max(...times);
  const span = Math.max(max - min, 1);

  // Inset so markers at the extremes are not clipped by the track edges.
  const pct = (iso: string) => {
    const t = new Date(iso).getTime();
    return 4 + ((t - min) / span) * 92;
  };

  const violations = calls.filter((c) => c.violations.length > 0);
  const phone = maskPhone(handleOf(entity, "phone"));
  const email = handleOf(entity, "email");
  const customerId = handleOf(entity, "customer_id");
  const disputeOpen = entity.state.dispute_status === "open";

  // Day ticks across the observed window.
  const dayCount = Math.max(1, Math.ceil(span / 86_400_000));
  const tickCount = Math.min(dayCount + 1, 7);
  const ticks = Array.from({ length: tickCount }, (_, i) => {
    const t = min + (span / Math.max(tickCount - 1, 1)) * i;
    return { at: new Date(t).toISOString(), left: 4 + (i / Math.max(tickCount - 1, 1)) * 92 };
  });

  return (
    <div className="timeline">
      <div className="timeline-head">
        <div className="who">
          <div className="name">{entity.display_name}</div>
          <div className="handles">
            {[customerId, phone, email].filter(Boolean).join("  ·  ")}
          </div>
        </div>
        <div className="spacer" />
        <div className="badges">
          <span className={`badge${entity.summary.agent_count > 1 ? " alert" : ""}`}>
            {entity.summary.agent_count} agents
          </span>
          <span className="badge">
            {entity.summary.promotional_contacts} contacts
          </span>
          <span
            className={`badge${entity.summary.discount_pct >= 15 ? " alert" : ""}`}
          >
            {entity.summary.discount_pct}% / 15% discount
          </span>
          {disputeOpen && <span className="badge alert">dispute open</span>}
          {entity.summary.violations > 0 && (
            <span className="badge alert">
              {entity.summary.violations} violation
              {entity.summary.violations === 1 ? "" : "s"}
            </span>
          )}
        </div>
      </div>

      <div className="lanes">
        {agents.map((agent) => {
          const laneCalls = calls.filter((c) => c.agent_id === agent.id);
          const color = LANE_COLOR[agent.id] ?? "var(--text-faint)";
          return (
            <div className="lane-row" key={agent.id}>
              <div className="lane-label">
                <span className="lane-swatch" style={{ background: color }} />
                {agent.display_name}
              </div>
              <div className="lane-track">
                {/* Violation markers span the lanes — the conflict is between agents. */}
                {violations.map((v) => (
                  <div
                    key={`v-${v.id}`}
                    className="violation-marker"
                    style={{ left: `${pct(v.sim_ts)}%` }}
                  />
                ))}
                {laneCalls.map((call) => (
                  <button
                    key={call.id}
                    className="event"
                    data-decision={call.decision}
                    data-selected={call.id === selectedCallId}
                    style={{ left: `${pct(call.sim_ts)}%`, background: color }}
                    onClick={() =>
                      onSelectCall(call.id === selectedCallId ? null : call.id)
                    }
                    title={`${formatDay(call.sim_ts)} ${formatTime(call.sim_ts)} · ${
                      call.tool
                    }${call.magnitude != null ? ` · ${call.magnitude}%` : ""} · ${
                      call.decision
                    }${
                      call.violations.length
                        ? ` — ${call.violations.map((v) => v.reason).join("; ")}`
                        : ""
                    }`}
                  />
                ))}
              </div>
            </div>
          );
        })}

        <div className="axis">
          <div />
          <div className="axis-track">
            {ticks.map((t, i) => (
              <span key={i} className="axis-tick" style={{ left: `${t.left}%` }}>
                {formatDay(t.at)}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
