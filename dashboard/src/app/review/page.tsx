"use client";

import { useEffect, useMemo, useState } from "react";

import Nav from "@/components/Nav";
import { LIVE_SOURCE, agentName, formatDay, formatTime, loadRun } from "@/lib/datasource";
import { getPolicy, submitReview, type Policy, type ReviewVerdict } from "@/lib/api";
import type { Call, RunData } from "@/lib/types";

/**
 * The review queue — what joins OBSERVE to ENFORCE.
 *
 * A dry run that tells you what WOULD have been stopped is half a loop. The other half
 * is you saying whether it should have been, and that judgement outliving the run. A rule
 * you keep marking wrong is a rule that needs changing, and that is a far better signal
 * than expecting anyone to read reason strings.
 *
 * Verdicts attach to a (call, rule) pair, not to a call: one call can breach two rules
 * and you may well agree with one and dispute the other.
 */

const VERDICTS: { value: ReviewVerdict; label: string; hint: string }[] = [
  { value: "correct", label: "Right call", hint: "Commons should stop this in ENFORCE" },
  { value: "incorrect", label: "Wrong call", hint: "this was fine — the rule needs changing" },
  { value: "unsure", label: "Not sure", hint: "come back to this" },
];

export default function ReviewPage() {
  const [data, setData] = useState<RunData | null>(null);
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [showDone, setShowDone] = useState(false);

  const load = () =>
    Promise.all([loadRun(LIVE_SOURCE), getPolicy()])
      .then(([run, p]) => {
        setData(run);
        setPolicy(p);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));

  useEffect(() => {
    load();
  }, []);

  // One row per (call, rule) that fired as a violation.
  const items = useMemo(() => {
    if (!data) return [];
    const out: { call: Call; ruleId: string; reason: string; verdict?: ReviewVerdict }[] = [];
    for (const call of data.calls) {
      for (const v of call.violations) {
        const existing = call.reviews?.find((r) => r.rule_id === v.rule_id);
        out.push({
          call,
          ruleId: v.rule_id,
          reason: v.reason,
          verdict: existing?.verdict as ReviewVerdict | undefined,
        });
      }
    }
    return out;
  }, [data]);

  const queue = showDone ? items : items.filter((i) => !i.verdict);
  const reviewed = items.filter((i) => i.verdict).length;

  const accuracy = useMemo(() => {
    const out: Record<string, { correct: number; incorrect: number; unsure: number }> = {};
    for (const i of items) {
      if (!i.verdict) continue;
      out[i.ruleId] ??= { correct: 0, incorrect: 0, unsure: 0 };
      out[i.ruleId][i.verdict] += 1;
    }
    return out;
  }, [items]);

  const decide = async (callId: number, ruleId: string, verdict: ReviewVerdict) => {
    const key = `${callId}:${ruleId}`;
    setPending(key);
    try {
      await submitReview({ call_id: callId, rule_id: ruleId, verdict, note: notes[key] ?? "" });
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPending(null);
    }
  };

  return (
    <>
      <Nav />
      <div className="shell">
        <h1>Review what Commons flagged</h1>
        <p className="lede">
          {policy?.mode === "OBSERVE"
            ? "Nothing here was stopped — Commons is only watching. Say whether each call should have been stopped, and that judgement carries into enforcement."
            : "Commons is enforcing. These are the calls it acted on; confirming or disputing them keeps the rules honest."}
        </p>

        {error && <div className="err">{error}</div>}
        {!data && !error && <div className="loading">loading decisions…</div>}

        {data && (
          <>
            <div className="stats">
              <div className="stat">
                <div className="label">Flagged</div>
                <div className="value">{items.length}</div>
                <div className="sub">rule breaches this run</div>
              </div>
              <div className="stat">
                <div className="label">Reviewed</div>
                <div className="value">{reviewed}</div>
                <div className="sub">{items.length - reviewed} still waiting</div>
              </div>
              {Object.entries(accuracy).map(([ruleId, a]) => (
                <div className="stat" key={ruleId}>
                  <div className="label">{ruleId.replace(/_/g, " ")}</div>
                  <div className={`value${a.incorrect > a.correct ? " alert" : ""}`}>
                    {a.correct}/{a.correct + a.incorrect}
                  </div>
                  <div className="sub">
                    {a.incorrect > a.correct
                      ? "mostly wrong — consider changing it"
                      : "you agreed with these"}
                  </div>
                </div>
              ))}
            </div>

            {Object.entries(accuracy).some(([, a]) => a.incorrect >= 2 && a.incorrect > a.correct) && (
              <div className="warn" style={{ marginTop: 18 }}>
                You have marked the same rule wrong more than once. That usually means the
                rule needs changing rather than the agents — worth editing it on the Rules
                page before switching enforcement on.
              </div>
            )}

            <h2>
              {showDone ? "All decisions" : "Waiting for you"}
              <button
                className="btn btn-quiet"
                style={{ marginLeft: 12 }}
                onClick={() => setShowDone((s) => !s)}
              >
                {showDone ? "show only unreviewed" : "show reviewed too"}
              </button>
            </h2>

            {queue.length === 0 ? (
              <div className="empty">
                {items.length === 0
                  ? "Nothing was flagged in this run."
                  : "Everything has been reviewed."}
              </div>
            ) : (
              queue.map(({ call, ruleId, reason, verdict }) => {
                const key = `${call.id}:${ruleId}`;
                return (
                  <section className="review-card" key={key} data-done={!!verdict}>
                    <div className="review-head">
                      <div>
                        <span className="mono" style={{ color: "var(--text-faint)" }}>
                          {formatDay(call.sim_ts)} {formatTime(call.sim_ts)}
                        </span>{" "}
                        <strong>{agentName(data.agents, call.agent_id)}</strong>{" "}
                        <span style={{ color: "var(--text-dim)" }}>
                          called <span className="mono">{call.tool}</span> on{" "}
                          {call.entity_ref}
                        </span>
                      </div>
                      <div className="spacer" />
                      <span className="badge alert">{ruleId.replace(/_/g, " ")}</span>
                    </div>

                    <div className="review-reason mono">{reason}</div>

                    {call.unattributed && (
                      <div className="warn">
                        This discount did not name an order or subscription, so Commons
                        could not tell it apart from a repeat of an earlier offer. The
                        breach may be double-counting one offer.
                      </div>
                    )}

                    {verdict ? (
                      <div className="review-done">
                        You said: <strong>{VERDICTS.find((v) => v.value === verdict)?.label}</strong>
                        <button
                          className="btn btn-quiet"
                          onClick={() => decide(call.id, ruleId, "unsure")}
                        >
                          change
                        </button>
                      </div>
                    ) : (
                      <>
                        <input
                          className="note-input"
                          placeholder="Why? (optional — helps when you revisit this rule)"
                          value={notes[key] ?? ""}
                          onChange={(e) =>
                            setNotes((n) => ({ ...n, [key]: e.target.value }))
                          }
                        />
                        <div className="review-actions">
                          {VERDICTS.map((v) => (
                            <button
                              key={v.value}
                              className={`btn btn-${v.value}`}
                              title={v.hint}
                              disabled={pending === key}
                              onClick={() => decide(call.id, ruleId, v.value)}
                            >
                              {v.label}
                            </button>
                          ))}
                        </div>
                      </>
                    )}
                  </section>
                );
              })
            )}
          </>
        )}
      </div>
    </>
  );
}
