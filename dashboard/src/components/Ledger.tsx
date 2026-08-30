"use client";

import { Fragment } from "react";

import type { Agent, Call, Rule, RuleFiring } from "@/lib/types";
import { agentName, formatDay, formatTime } from "@/lib/datasource";

/**
 * The conflict ledger.
 *
 * Chronological, every decision, expandable to the full request and response. Every
 * violation ships with a replayable trace rather than asking anyone to trust an
 * aggregate. This is where that promise is kept.
 *
 * The expanded panel used to be JSON.stringify of the whole call. That is the right
 * content and the wrong reader: the person who needs to understand why a payment was
 * stopped is a merchant, not the engineer who wrote the gateway. So the trace now leads
 * with four plain questions -- what was asked, who it affects, what the policy said,
 * what happened -- and keeps the raw record underneath for whoever wants to verify it.
 */

interface Props {
  calls: Call[];
  agents: Agent[];
  selectedCallId: number | null;
  onSelectCall: (id: number | null) => void;
  violationsOnly?: boolean;
  /** Lets a firing be shown as the sentence the merchant wrote, not just a rule id. */
  rules?: Rule[];
  /** The customer these calls belong to, when the page is scoped to one. */
  entityName?: string;
}

/** What the action does to a person, in the merchant's words rather than the vendor's. */
const ACTION_PHRASE: Record<string, string> = {
  discount_grant: "give this customer a discount",
  promotional_message: "send this customer a marketing message",
  transactional_message: "send this customer a service message",
  fulfilment_restriction: "restrict how this order can be paid for",
  refund: "refund this customer",
  dispute_action: "act on this customer's dispute",
  read: "look something up",
};

const VERDICT_WORD: Record<string, string> = {
  ALLOW: "Allowed",
  DEFER: "Held back",
  BLOCK: "Blocked",
};

function describeRequest(call: Call, agents: Agent[]): string {
  const who = agentName(agents, call.agent_id);
  const what = call.action_class
    ? ACTION_PHRASE[call.action_class] ?? call.action_class.replace(/_/g, " ")
    : "call a tool it has not declared";
  return `${who} asked ${call.upstream} to ${what}.`;
}

/** The one or two details that actually matter, pulled out of the argument blob. */
function highlights(call: Call): [string, string][] {
  const out: [string, string][] = [];
  const args = (call.args ?? {}) as Record<string, unknown>;

  if (call.magnitude != null) {
    const unit = call.magnitude_unit === "percent" ? "%" : "";
    out.push(["Amount given away", `${call.magnitude}${unit}`]);
  }
  const amount = args.amount;
  if (typeof amount === "number") {
    out.push(["Order value", `Rs ${(amount / 100).toLocaleString("en-IN")}`]);
  }
  const subject = args.subject ?? args.description;
  if (typeof subject === "string" && subject) {
    out.push(["Message", subject]);
  }
  if (call.resource) {
    out.push(["Applies to", call.resource]);
  }
  return out;
}

function outcomeLine(call: Call): { text: string; tone: "ok" | "warn" | "bad" } {
  if (!call.forwarded) {
    return {
      text: `Stopped by Commons. ${call.upstream} never received this call.`,
      tone: "bad",
    };
  }
  if (call.is_error) {
    return {
      text: `Sent to ${call.upstream}, which rejected it. Nothing reached the customer, and nothing was counted against their limits.`,
      tone: "warn",
    };
  }
  return { text: `Sent to ${call.upstream} and accepted.`, tone: "ok" };
}

function resultText(result: unknown): string {
  if (result == null) return "";
  if (typeof result === "string") return result;
  try {
    return JSON.stringify(result, null, 2);
  } catch {
    return String(result);
  }
}

function Firing({ firing, rules }: { firing: RuleFiring; rules?: Rule[] }) {
  const english = rules?.find((r) => r.id === firing.rule_id)?.english;
  return (
    <div className="tr-rule" data-v={firing.verdict}>
      <div className="tr-rule-head">
        <span className="verdict" data-v={firing.verdict}>
          {VERDICT_WORD[firing.verdict] ?? firing.verdict}
        </span>
        <span className="tr-rule-name">{english ?? firing.rule_id}</span>
      </div>
      <div className="tr-rule-why">{firing.reason}</div>
      {firing.observed != null && firing.limit != null && (
        <div className="tr-rule-num">
          Reached <strong>{firing.observed}</strong> against a limit of{" "}
          <strong>{firing.limit}</strong>
        </div>
      )}
    </div>
  );
}

export default function Ledger({
  calls,
  agents,
  selectedCallId,
  onSelectCall,
  violationsOnly = false,
  rules,
  entityName,
}: Props) {
  const rows = violationsOnly ? calls.filter((c) => c.violations.length > 0) : calls;

  if (rows.length === 0) {
    return <div className="empty">No calls.</div>;
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
            const outcome = outcomeLine(call);
            const detail = highlights(call);
            const raw = resultText(call.result);
            return (
              // A row and its expanded trace are two <tr>s for one call, so the key belongs
              // on the Fragment that wraps them, not on the first <tr>.
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
                        {" · "}
                        {call.action_class.replace(/_/g, " ")}
                      </span>
                    )}
                    {call.unattributed && (
                      <span
                        style={{ color: "var(--defer)" }}
                        title="No order or subscription named, so this could not be recognised as a re-offer and was counted as a separate giveaway."
                      >
                        {" · unattributed"}
                      </span>
                    )}
                    {call.violations.map((v, i) => (
                      <div className="reason" key={i}>
                        {v.rule_id}: {v.reason}
                      </div>
                    ))}
                  </td>
                  <td className="num">
                    {call.magnitude != null
                      ? `${call.magnitude}${call.magnitude_unit === "percent" ? "%" : ""}`
                      : ""}
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
                      <div className="tr">
                        <section className="tr-block">
                          <h4>What the agent asked for</h4>
                          <p className="tr-lead">{describeRequest(call, agents)}</p>
                          {detail.length > 0 && (
                            <dl className="tr-facts">
                              {detail.map(([k, v]) => (
                                <Fragment key={k}>
                                  <dt>{k}</dt>
                                  <dd>{v}</dd>
                                </Fragment>
                              ))}
                            </dl>
                          )}
                        </section>

                        <section className="tr-block">
                          <h4>Who it affects</h4>
                          {call.entity_ref || entityName ? (
                            <p className="tr-lead">
                              {entityName ?? "This customer"}
                              {call.entity_ref && (
                                <span className="tr-sub">
                                  {" "}
                                  recognised from <span className="mono">{call.entity_ref}</span>
                                </span>
                              )}
                            </p>
                          ) : (
                            <p className="tr-lead tr-muted">
                              No customer named in this call, so no rule about a person
                              could apply to it.
                            </p>
                          )}
                        </section>

                        <section className="tr-block">
                          <h4>What your policy said</h4>
                          {call.rules_fired.length === 0 ? (
                            <p className="tr-lead tr-muted">
                              Every rule was checked and none of them had anything to say
                              about this call.
                            </p>
                          ) : (
                            call.rules_fired.map((f, i) => (
                              <Firing key={i} firing={f} rules={rules} />
                            ))
                          )}
                        </section>

                        <section className="tr-block">
                          <h4>What happened</h4>
                          <p className="tr-lead" data-tone={outcome.tone}>
                            {outcome.text}
                          </p>
                          {call.latency_ms != null && (
                            <p className="tr-sub">
                              Commons added {call.latency_ms} ms to this call.
                            </p>
                          )}
                        </section>

                        <details className="tr-raw">
                          <summary>Raw request and response</summary>
                          <pre>
                            {JSON.stringify(
                              {
                                entity: call.entity_ref,
                                resource: call.resource,
                                arguments: call.args,
                                rules_evaluated: call.rules_fired,
                                forwarded: call.forwarded,
                                latency_ms: call.latency_ms,
                              },
                              null,
                              2
                            )}
                            {raw && `\n\nresponse:\n${raw}`}
                          </pre>
                        </details>
                      </div>
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
