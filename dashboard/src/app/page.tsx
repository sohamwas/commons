"use client";

import { useEffect, useMemo, useState } from "react";
import Ledger from "@/components/Ledger";
import Timeline from "@/components/Timeline";
import {
  LIVE_SOURCE,
  RECORDED_RUNS,
  loadRun,
  handleOf,
  maskPhone,
  type Source,
} from "@/lib/datasource";
import type { RunData } from "@/lib/types";

const LANE_COLOR: Record<string, string> = {
  "cart-recovery": "var(--agent-cart)",
  "subscription-recovery": "var(--agent-subscription)",
  "dispute-responder": "var(--agent-dispute)",
  "rto-shield": "var(--agent-rto)",
};

export default function Page() {
  const [mode, setMode] = useState<"observe" | "enforce" | "live">("observe");
  const [data, setData] = useState<RunData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [entityId, setEntityId] = useState<string | null>(null);
  const [callId, setCallId] = useState<number | null>(null);

  useEffect(() => {
    const source: Source =
      mode === "live" ? LIVE_SOURCE : RECORDED_RUNS[mode];
    setData(null);
    setError(null);
    loadRun(source)
      .then((d) => {
        setData(d);
        setEntityId((current) => {
          // Keep the same customer selected when flipping modes — the whole point is
          // to watch ONE person's timeline change.
          if (current && d.entities.some((e) => e.id === current)) return current;
          return d.entities[0]?.id ?? null;
        });
        setCallId(null);
      })
      .catch((e: Error) => setError(e.message));
  }, [mode]);

  const entity = useMemo(
    () => data?.entities.find((e) => e.id === entityId) ?? null,
    [data, entityId]
  );

  const entityCalls = useMemo(() => {
    if (!data || !entity) return [];
    return data.calls.filter((c) => c.entity_id === entity.id);
  }, [data, entity]);

  return (
    <>
      <header className="top">
        <div className="top-inner">
          <div className="wordmark">
            Commons<span>arbitration gateway</span>
          </div>
          <div className="spacer" />
          {data && (
            <div
              className="mono"
              style={{ fontSize: 11, color: "var(--text-faint)" }}
            >
              seed {data.run.seed ?? "—"} · {data.stats.calls} calls
            </div>
          )}
          <div className="modes">
            {(["observe", "enforce", "live"] as const).map((m) => (
              <button
                key={m}
                data-mode={m.toUpperCase()}
                data-active={mode === m}
                onClick={() => setMode(m)}
              >
                {m.toUpperCase()}
              </button>
            ))}
          </div>
        </div>
      </header>

      <div className="shell">
        <h1>Who is being acted upon</h1>
        <p className="thesis">
          Every agent platform scopes permissions to the <strong>agent</strong>. None
          scope limits to the <strong>customer</strong>. The moment a merchant runs more
          than one agent, its real exposure lives somewhere nothing can see.
        </p>

        {error && (
          <div className="err">
            {error}
            {mode === "live" && (
              <div style={{ marginTop: 8, color: "var(--text-dim)" }}>
                Start the proxy: <span className="mono">
                  python scripts/run_proxy.py
                </span>
              </div>
            )}
          </div>
        )}

        {!data && !error && <div className="loading">loading run…</div>}

        {data && (
          <>
            <div className="stats">
              <div className="stat">
                <div className="label">Customers</div>
                <div className="value">{data.stats.entities}</div>
                <div className="sub">acted upon this run</div>
              </div>
              <div className="stat">
                <div className="label">Worked by 2+ agents</div>
                <div className="value alert">{data.stats.multi_agent_entities}</div>
                <div className="sub">no agent can see this</div>
              </div>
              <div className="stat">
                <div className="label">Tool calls</div>
                <div className="value">{data.stats.calls}</div>
                <div className="sub">{data.stats.forwarded} reached the vendor</div>
              </div>
              <div className="stat">
                <div className="label">Stopped by Commons</div>
                <div className={`value${data.stats.stopped ? " alert" : ""}`}>
                  {data.stats.stopped}
                </div>
                <div className="sub">
                  {data.run.mode === "OBSERVE"
                    ? "observing only"
                    : "policy enforced"}
                </div>
              </div>
              <div className="stat">
                <div className="label">Violations</div>
                <div className={`value${data.stats.violations ? " alert" : ""}`}>
                  {data.stats.violations}
                </div>
                <div className="sub">across all agents</div>
              </div>
            </div>

            <h2>Customers, ranked by how contested they are</h2>
            <div className="customer-grid">
              {data.entities.slice(0, 12).map((e) => (
                <button
                  key={e.id}
                  className="customer-card"
                  data-selected={e.id === entityId}
                  onClick={() => {
                    setEntityId(e.id);
                    setCallId(null);
                  }}
                >
                  <div className="name">{e.display_name}</div>
                  <div className="ref">
                    {handleOf(e, "customer_id") ??
                      maskPhone(handleOf(e, "phone"))}
                  </div>
                  <div className="pips">
                    {data.agents.map((a) => (
                      <span
                        key={a.id}
                        className="pip"
                        style={
                          e.agents.includes(a.id)
                            ? { background: LANE_COLOR[a.id] }
                            : undefined
                        }
                      />
                    ))}
                  </div>
                  <div className="card-meta">
                    <span>{e.summary.agent_count} agents</span>
                    <span>{e.summary.discount_pct}%</span>
                    {e.summary.violations > 0 && (
                      <span className="bad">
                        {e.summary.violations}!
                      </span>
                    )}
                  </div>
                </button>
              ))}
            </div>

            <h2>One customer, every agent</h2>
            {entity ? (
              <Timeline
                entity={entity}
                calls={entityCalls}
                agents={data.agents}
                selectedCallId={callId}
                onSelectCall={setCallId}
              />
            ) : (
              <div className="empty">Select a customer.</div>
            )}
            <p className="note">
              Four lanes, one human. Each agent is doing exactly the job it was built
              for, and each one is individually correct. The dashed marks are where
              their actions collide — which is between the lanes, where no single agent
              is looking.
            </p>

            <h2>Conflict ledger — {entity?.display_name ?? "all"}</h2>
            <Ledger
              calls={entityCalls}
              agents={data.agents}
              selectedCallId={callId}
              onSelectCall={setCallId}
            />
            <p className="note">
              Click any row for the full trace: the arguments sent, every rule evaluated,
              and whether the call reached the vendor. No aggregate asks to be trusted.
            </p>
          </>
        )}
      </div>
    </>
  );
}
