"use client";

import { useCallback, useEffect, useState } from "react";

import Nav from "@/components/Nav";
import {
  PROXY_URL,
  addAgent,
  getAgents,
  getHealth,
  removeAgent,
  type Agent,
  type Health,
} from "@/lib/api";

/**
 * Onboarding.
 *
 * Registering an agent is a merchant action, done here, served immediately. It used to
 * mean editing registry.py and restarting a gateway the other agents were connected to.
 *
 * Adoption is then one line per agent: point it at its Commons URL instead of the
 * vendor's. Nothing inside the agent changes, which is the whole reason the proxy sits
 * where it does. It works for agents whose source you cannot touch.
 */

function Copyable({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="snippet">
      <pre>{text}</pre>
      <button
        className="btn btn-quiet"
        onClick={() => {
          navigator.clipboard?.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1800);
        }}
      >
        {copied ? "copied" : "copy"}
      </button>
    </div>
  );
}

export default function ConnectPage() {
  const [health, setHealth] = useState<Health | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [vendors, setVendors] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [tools, setTools] = useState<Record<string, string>>({});

  const load = useCallback(
    () =>
      Promise.all([getHealth(), getAgents()])
        .then(([h, a]) => {
          setHealth(h);
          setAgents(a.agents);
          setVendors(a.vendors);
          setError(null);
        })
        .catch((e: Error) => setError(e.message)),
    []
  );

  useEffect(() => {
    load();
  }, [load]);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      // Comma or whitespace separated, because that is how people type a list.
      const payload: Record<string, string[]> = {};
      for (const [vendor, raw] of Object.entries(tools)) {
        const names = raw.split(/[,\s]+/).map((s) => s.trim()).filter(Boolean);
        if (names.length) payload[vendor] = names;
      }
      await addAgent({ id: id.trim().toLowerCase(), display_name: name.trim(), tools: payload });
      setId("");
      setName("");
      setTools({});
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const drop = async (agentId: string) => {
    setError(null);
    try {
      await removeAgent(agentId);
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const ready = id.trim() && Object.values(tools).some((v) => v.trim());

  return (
    <>
      <Nav />
      <div className="shell">
        <h1>Connect</h1>
        <p className="lede">
          Register an agent, then replace the vendor URL in its MCP config with the URL
          below. Nothing inside the agent changes.
        </p>

        {error && <div className="err">{error}</div>}

        {health && Object.keys(health.unavailable).length > 0 && (
          <div className="warn">
            {Object.entries(health.unavailable).map(([vendor, why]) => (
              <div key={vendor}>
                <strong>{vendor}</strong> is not reachable: <span className="mono">{why}</span>
              </div>
            ))}
            Agents can still be registered against the vendors that are up.
          </div>
        )}

        <h2>Add an agent</h2>
        <div className="agent-form">
          <label className="field">
            <span className="field-label">Id</span>
            <input
              className="mono"
              value={id}
              placeholder="cart-recovery"
              onChange={(e) => setId(e.target.value)}
            />
            <span className="field-hint">lowercase, used in the URL</span>
          </label>

          <label className="field">
            <span className="field-label">Name</span>
            <input
              value={name}
              placeholder="Cart Recovery"
              onChange={(e) => setName(e.target.value)}
            />
            <span className="field-hint">optional</span>
          </label>

          {vendors.map((vendor) => (
            <label className="field" key={vendor}>
              <span className="field-label">{vendor} tools</span>
              <input
                className="mono"
                value={tools[vendor] ?? ""}
                placeholder="create_payment_link, fetch_order"
                onChange={(e) => setTools((t) => ({ ...t, [vendor]: e.target.value }))}
              />
              <span className="field-hint">only what this agent needs</span>
            </label>
          ))}
        </div>

        <div className="review-actions">
          <button className="btn" disabled={!ready || busy} onClick={submit}>
            {busy ? "adding" : "Add agent"}
          </button>
        </div>

        <h2>Registered ({agents.length})</h2>
        {agents.length === 0 ? (
          <div className="empty">
            None yet. Add one above and its endpoints appear here immediately.
          </div>
        ) : (
          agents.map((agent) => (
            <section className="rule" key={agent.id}>
              <div className="rule-head">
                <div style={{ flex: 1 }}>
                  <strong>{agent.display_name}</strong>
                  <div className="rule-compiled mono">
                    {Object.entries(agent.tools)
                      .map(([v, names]) => `${v}: ${names.join(", ")}`)
                      .join("   ·   ")}
                  </div>
                </div>
                <button className="btn btn-quiet" onClick={() => drop(agent.id)}>
                  remove
                </button>
              </div>
              {agent.endpoints.map((path) => {
                const vendor = path.split("/")[3];
                return (
                  <Copyable
                    key={path}
                    text={JSON.stringify(
                      { mcpServers: { [vendor]: { url: `${PROXY_URL}${path}` } } },
                      null,
                      2
                    )}
                  />
                );
              })}
            </section>
          ))
        )}

        <h2>Then</h2>
        <ol className="steps">
          <li>
            Calls appear on <a href="/">Customers</a>. Nothing there means the agent is
            still talking to the vendor.
          </li>
          <li>
            Import your customer list on <a href="/data">Data</a> so calls from different
            vendors resolve to one person.
          </li>
          <li>
            Stay in OBSERVE. Work through <a href="/review">Review</a>, then switch to
            ENFORCE from the header.
          </li>
        </ol>

        <p className="note">
          Commons runs on your machine. Nothing leaves your network except the calls your
          agents were already making.
        </p>
      </div>
    </>
  );
}
