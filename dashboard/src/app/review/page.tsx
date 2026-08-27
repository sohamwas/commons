"use client";

import { useEffect, useMemo, useState } from "react";

import Nav from "@/components/Nav";
import { LIVE_SOURCE, agentName, formatDay, formatTime, loadRun } from "@/lib/datasource";
import { submitReview, type ReviewVerdict } from "@/lib/api";
import type { Call, RunData } from "@/lib/types";

/**
 * The review queue, which is what joins OBSERVE to ENFORCE.
 *
 * A dry run that tells you what WOULD have been stopped is half a loop. The other half is
 * you saying whether it should have been, and that judgement outliving the run.
 *
 * Verdicts attach to a (call, rule) pair, not to a call: one call can breach two rules and
 * you may agree with one and dispute the other.
 */

function existingNote(call: Call, ruleId: string): string | undefined {
  return call.reviews?.find((r) => r.rule_id === ruleId)?.note ?? undefined;
}

const VERDICTS: { value: ReviewVerdict; label: string; hint: string }[] = [
  { value: "correct", label: "Right", hint: "Stop this in ENFORCE" },
  { value: "incorrect", label: "Wrong", hint: "This was fine. The rule needs changing." },
  { value: "unsure", label: "Unsure", hint: "Come back to this" },
];

export default function ReviewPage() {
  const [data, setData] = useState<RunData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [showDone, setShowDone] = useState(false);
  // Keys currently being re-decided. "Change" previously wrote "unsure" straight away,
  // which threw the old answer away and still gave no way to pick a new one, so a verdict
  // was effectively permanent. It should reopen the choice, not overwrite it.
  const [editing, setEditing] = useState<Set<string>>(new Set());

  const reopen = (key: string) => setEditing((s) => new Set(s).add(key));

  const closeEditing = (key: string) =>
    setEditing((s) => {
      const next = new Set(s);
      next.delete(key);
      return next;
    });

  const load = () =>
    loadRun(LIVE_SOURCE)
      .then((run) => {
        setData(run);
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
      closeEditing(key);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPending(null);
    }
  };

  // A rule you keep marking wrong is a rule that needs changing, not agents that do.
  const suspect = Object.entries(accuracy).filter(
    ([, a]) => a.incorrect >= 2 && a.incorrect > a.correct
  );

  return (
    <>
      <Nav />
      <div className="shell">
        <h1>Review</h1>

        {error && <div className="err">{error}</div>}
        {!data && !error && <div className="loading">loading</div>}

        {data && (
          <>
            <div className="stats">
              <div className="stat">
                <div className="label">Flagged</div>
                <div className="value">{items.length}</div>
              </div>
              <div className="stat">
                <div className="label">Reviewed</div>
                <div className="value">
                  {reviewed}/{items.length}
                </div>
              </div>
              {Object.entries(accuracy).map(([ruleId, a]) => (
                <div className="stat" key={ruleId}>
                  <div className="label">{ruleId.replace(/_/g, " ")}</div>
                  <div className={`value${a.incorrect > a.correct ? " alert" : ""}`}>
                    {a.correct}/{a.correct + a.incorrect}
                  </div>
                  <div className="sub">agreed</div>
                </div>
              ))}
            </div>

            {suspect.length > 0 && (
              <div className="warn">
                {suspect.map(([id]) => id.replace(/_/g, " ")).join(", ")} is mostly wrong.
                Edit it on Rules before enforcing.
              </div>
            )}

            <h2>
              {showDone ? "All" : "Waiting"}
              <button className="btn btn-quiet" onClick={() => setShowDone((s) => !s)}>
                {showDone ? "unreviewed only" : "show all"}
              </button>
            </h2>

            {queue.length === 0 ? (
              <div className="empty">
                {items.length === 0 ? "Nothing flagged." : "All reviewed."}
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
                        <span className="mono" style={{ color: "var(--text-dim)" }}>
                          {call.tool}
                        </span>{" "}
                        <span style={{ color: "var(--text-dim)" }}>{call.entity_ref}</span>
                      </div>
                      <div className="spacer" />
                      <span className="badge alert">{ruleId.replace(/_/g, " ")}</span>
                    </div>

                    <div className="review-reason mono">{reason}</div>

                    {call.unattributed && (
                      <div className="warn">
                        No order or subscription named, so this may be one offer counted
                        twice.
                      </div>
                    )}

                    {verdict && !editing.has(key) ? (
                      <div className="review-done">
                        <strong>{VERDICTS.find((v) => v.value === verdict)?.label}</strong>
                        {existingNote(call, ruleId) && (
                          <span style={{ color: "var(--text-faint)" }}>
                            {existingNote(call, ruleId)}
                          </span>
                        )}
                        <button className="btn btn-quiet" onClick={() => reopen(key)}>
                          change
                        </button>
                      </div>
                    ) : (
                      <>
                        <input
                          className="note-input"
                          placeholder="Note (optional)"
                          value={notes[key] ?? existingNote(call, ruleId) ?? ""}
                          onChange={(e) => setNotes((n) => ({ ...n, [key]: e.target.value }))}
                        />
                        <div className="review-actions">
                          {VERDICTS.map((v) => (
                            <button
                              key={v.value}
                              className={`btn btn-${v.value}`}
                              data-current={v.value === verdict}
                              title={v.hint}
                              disabled={pending === key}
                              onClick={() => decide(call.id, ruleId, v.value)}
                            >
                              {v.label}
                            </button>
                          ))}
                          {verdict && (
                            <button className="btn btn-quiet" onClick={() => closeEditing(key)}>
                              cancel
                            </button>
                          )}
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
