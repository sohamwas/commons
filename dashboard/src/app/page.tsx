"use client";

import { useEffect, useMemo, useState } from "react";
import Ledger from "@/components/Ledger";
import Nav from "@/components/Nav";
import Timeline from "@/components/Timeline";
import {
  LIVE_SOURCE,
  loadRun,
  handleOf,
  laneColor,
  maskPhone,
} from "@/lib/datasource";
import type { Entity, RunData } from "@/lib/types";

// A merchant can have thousands. Render a page of them and let search reach the rest.
const SHOWN = 60;

/**
 * An order id on its own is not a person.
 *
 * When a tool names only an order or subscription and the merchant has not declared who
 * it belongs to, Commons still has to attribute the call to something, so it mints an
 * entity keyed on that id. Those are real, and they carry real agent activity, but
 * listing them as customers is wrong: nobody has a customer called sub_4475.
 */
function identified(e: Entity): boolean {
  return e.handles.some(([ns]) => ns !== "order_id");
}

/**
 * The merchant's own customers.
 *
 * Reads the LIVE proxy and nothing else. This page used to offer a choice between two
 * recorded runs and the live one, which conflated two unrelated things: OBSERVE and
 * ENFORCE are gateway MODES a merchant moves between over time (watch, review, then
 * enforce), not datasets to flip between. The two recordings are demo evidence and
 * belong on the marketing site, not in the tool a merchant runs on their own machine.
 */
export default function Page() {
  const [data, setData] = useState<RunData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [entityId, setEntityId] = useState<string | null>(null);
  const [callId, setCallId] = useState<number | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    setData(null);
    setError(null);
    loadRun(LIVE_SOURCE)
      .then((d) => {
        setData(d);
        setEntityId((current) => {
          // Keep the selection across refreshes rather than snapping back to the top.
          if (current && d.entities.some((e) => e.id === current)) return current;
          return d.entities[0]?.id ?? null;
        });
        setCallId(null);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  const entity = useMemo(
    () => data?.entities.find((e) => e.id === entityId) ?? null,
    [data, entityId]
  );

  const customers = useMemo(() => {
    if (!data) return [];
    const q = query.trim().toLowerCase();
    const ranked = [...data.entities].sort(
      (a, b) => Number(identified(b)) - Number(identified(a))
    );
    if (!q) return ranked;
    return ranked.filter(
      (e) =>
        e.display_name.toLowerCase().includes(q) ||
        e.handles.some(([, v]) => v.toLowerCase().includes(q))
    );
  }, [data, query]);

  // The stat said "Customers" and counted order ids among them.
  const people = useMemo(
    () => (data ? data.entities.filter(identified).length : 0),
    [data]
  );

  const entityCalls = useMemo(() => {
    if (!data || !entity) return [];
    return data.calls.filter((c) => c.entity_id === entity.id);
  }, [data, entity]);

  return (
    <>
      <Nav />

      <div className="shell">
        <h1>Customers</h1>


        {error && (
          <div className="err">
            {error}
            <div className="mono">python scripts/run_proxy.py</div>
          </div>
        )}

        {!data && !error && <div className="loading">loading</div>}

        {data && (
          <>
            <div className="stats">
              <div className="stat">
                <div className="label">Customers</div>
                <div className="value">{people}</div>
                {people < data.entities.length && (
                  <div className="sub">
                    +{data.entities.length - people} unidentified
                  </div>
                )}
              </div>
              <div className="stat">
                <div className="label">2+ agents</div>
                <div className="value alert">{data.stats.multi_agent_entities}</div>
              </div>
              <div className="stat">
                <div className="label">Calls</div>
                <div className="value">{data.stats.calls}</div>
              </div>
              <div className="stat">
                <div className="label">Forwarded</div>
                <div className="value">{data.stats.forwarded}</div>
              </div>
              <div className="stat">
                <div className="label">Stopped</div>
                <div className={`value${data.stats.stopped ? " alert" : ""}`}>
                  {data.stats.stopped}
                </div>
              </div>
              <div className="stat">
                <div className="label">Violations</div>
                <div className={`value${data.stats.violations ? " alert" : ""}`}>
                  {data.stats.violations}
                </div>
              </div>
            </div>

            <div className="list-head">
              <input
                className="search"
                placeholder="Search name, phone, email or id"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                spellCheck={false}
              />
              <span className="count">
                {customers.length === data.entities.length
                  ? `${data.entities.length} customers`
                  : `${customers.length} of ${data.entities.length}`}
                {customers.length > SHOWN && ` · showing ${SHOWN}, search to narrow`}
              </span>
            </div>

            {customers.length === 0 && (
              <div className="empty">No customer matches that.</div>
            )}

            <div className="customer-grid">
              {customers.slice(0, SHOWN).map((e) => (
                <button
                  key={e.id}
                  className="customer-card"
                  data-selected={e.id === entityId}
                  data-unidentified={!identified(e)}
                  onClick={() => {
                    setEntityId(e.id);
                    setCallId(null);
                  }}
                >
                  <div className="name">
                    {identified(e) ? e.display_name : "Unidentified"}
                  </div>
                  <div className="ref">
                    {identified(e)
                      ? handleOf(e, "customer_id") ?? maskPhone(handleOf(e, "phone"))
                      : handleOf(e, "order_id")}
                  </div>
                  <div className="pips">
                    {data.agents.map((a, i) => (
                      <span
                        key={a.id}
                        className="pip"
                        style={
                          e.agents.includes(a.id)
                            ? { background: laneColor(a.id, i) }
                            : undefined
                        }
                      />
                    ))}
                  </div>
                  <div className="card-meta">
                    <span>{e.summary.agent_count} agents</span>
                    <span>{e.summary.discount_pct}%</span>
                    {e.summary.violations > 0 && (
                      <span className="bad">{e.summary.violations}!</span>
                    )}
                  </div>
                </button>
              ))}
            </div>

            <h2>Timeline</h2>
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

            <h2>Calls</h2>
            <Ledger
              calls={entityCalls}
              agents={data.agents}
              selectedCallId={callId}
              onSelectCall={setCallId}
            />
          </>
        )}
      </div>
    </>
  );
}
