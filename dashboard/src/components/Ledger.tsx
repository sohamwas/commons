"use client";

import { Fragment } from "react";

import type { Agent, Call } from "@/lib/types";
import { agentName, formatDay, formatTime } from "@/lib/datasource";

/**
 * The conflict ledger.
 *
 * Chronological, every decision, expandable to the full request and response. Handoff
 * §17.4 promises that every violation ships with a replayable trace rather than asking
 * anyone to trust an aggregate — this is where that promise is kept.
 */

interface Props {
  calls: Call[];
  agents: Agent[];
  selectedCallId: number | null;
  onSelectCall: (id: number | null) => void;
  violationsOnly?: boolean;
}

export default function Ledger({
  calls,
  agents,
  selectedCallId,
  onSelectCall,
  violationsOnly = false,
}: Props) {
  const rows = violationsOnly ? calls.filter((c) => c.violations.length > 0) : calls;

  if (rows.length === 0) {
    return (
      <div className="empty">
        {violationsOnly ? "No violations in this run." : "No calls recorded."}
      </div>
    );
  }

  return (
    <div className="ledger">
      <table>
        <thead>
          <tr>
            <th style={{ width: 96 }}>When</th>
            <th style={{ width: 170 }}>Agent</th>
            <th style={{ width: 90 }}>Vendor</th>
            <th>Action</th>
            <th style={{ width: 72 }} className="num">
              Amount
            </th>
            <th style={{ width: 84 }}>Decision</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((call) => {
            const open = call.id === selectedCallId;
            return (
              // A row and its expanded trace are two <tr>s for one call, so the key
              // belongs on the Fragment that wraps them — not on the first <tr>.
              <Fragment key={call.id}>
                <tr
                  data-violation={call.violations.length > 0}
                  onClick={() => onSelectCall(open ? null : call.id)}
                >
                  <td className="num" style={{ color: "var(--text-faint)" }}>
                    {formatDay(call.sim_ts)}
                    <br />
                    {formatTime(call.sim_ts)}
                  </td>
                  <td>{agentName(agents, call.agent_id)}</td>
                  <td style={{ color: "var(--text-dim)" }}>{call.upstream}</td>
                  <td>
                    <span className="mono">{call.tool}</span>
                    {call.action_class && (
                      <span style={{ color: "var(--text-faint)" }}>
                        {" "}
                        · {call.action_class.replace(/_/g, " ")}
                      </span>
                    )}
                    {call.unattributed && (
                      <div
                        style={{
                          fontSize: 11.5,
                          color: "var(--defer)",
                          fontFamily: "var(--mono)",
                          marginTop: 3,
                        }}
                        title="No order or subscription named, so this could not be recognised as a re-offer and was counted as a separate giveaway."
                      >
                        no order/subscription named — counted as a separate giveaway
                      </div>
                    )}
                    {call.violations.map((v, i) => (
                      <div className="reason" key={i}>
                        {v.rule_id}: {v.reason}
                      </div>
                    ))}
                  </td>
                  <td className="num">
                    {call.magnitude != null
                      ? `${call.magnitude}${
                          call.magnitude_unit === "percent" ? "%" : ""
                        }`
                      : "—"}
                  </td>
                  <td>
                    <span className="verdict" data-v={call.decision}>
                      {call.decision}
                    </span>
                    {!call.forwarded && (
                      <div
                        style={{
                          fontSize: 10.5,
                          color: "var(--danger)",
                          fontFamily: "var(--mono)",
                        }}
                      >
                        stopped
                      </div>
                    )}
                  </td>
                </tr>
                {open && (
                  <tr className="trace">
                    <td colSpan={6}>
                      <pre>
                        {JSON.stringify(
                          {
                            entity: call.entity_ref,
                            resource: call.resource,
                            arguments: call.args,
                            rules_evaluated: call.rules_fired,
                            forwarded: call.forwarded,
                            latency_ms: call.latency_ms,
                            result: call.result,
                          },
                          null,
                          2
                        )}
                      </pre>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
