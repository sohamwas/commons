"use client";

import { useCallback, useEffect, useState } from "react";

import Nav from "@/components/Nav";
import {
  PROXY_URL,
  addAgent,
  ALL_TOOLS,
  addVendor,
  getAgents,
  getVendorTools,
  getVendors,
  removeAgent,
  removeVendor,
  type Agent,
  type Vendor,
  type VendorTool,
} from "@/lib/api";

/**
 * Onboarding: vendors, then agents.
 *
 * Both are merchant actions done here and served immediately. Both used to be hardcoded
 * in Python, which made Commons a Razorpay-and-messaging tool rather than an arbitration
 * layer for whatever a merchant actually runs.
 *
 * Tools are TICKED, not typed. The vendor publishes its catalogue and Commons knows which
 * of those tools it has semantics for, so asking a merchant to remember tool names was
 * asking them for something the software already had.
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
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [catalogue, setCatalogue] = useState<Record<string, VendorTool[]>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // add vendor
  const [vName, setVName] = useState("");
  const [vUrl, setVUrl] = useState("");
  const [vHeader, setVHeader] = useState("");
  const [showVendorForm, setShowVendorForm] = useState(false);

  // add agent
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [picked, setPicked] = useState<Record<string, Set<string>>>({});
  // Narrowing an allowlist is a security decision. Putting one in front of someone before
  // they have seen the thing work is the wrong order, so full access is the default and
  // this opens the picker for anyone who wants to tighten it now.
  const [narrowing, setNarrowing] = useState(false);

  const load = useCallback(async () => {
    try {
      const [v, a] = await Promise.all([getVendors(), getAgents()]);
      setVendors(v.vendors);
      setAgents(a.agents);
      setError(null);

      const tools: Record<string, VendorTool[]> = {};
      await Promise.all(
        v.vendors
          .filter((x) => x.connected)
          .map(async (x) => {
            try {
              tools[x.name] = (await getVendorTools(x.name)).tools;
            } catch {
              tools[x.name] = [];
            }
          })
      );
      setCatalogue(tools);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const toggle = (vendor: string, tool: string) =>
    setPicked((p) => {
      const next = new Set(p[vendor] ?? []);
      if (next.has(tool)) next.delete(tool);
      else next.add(tool);
      return { ...p, [vendor]: next };
    });

  const submitVendor = async () => {
    setBusy(true);
    setError(null);
    try {
      const headers: Record<string, string> = {};
      if (vHeader.trim()) {
        const [k, ...rest] = vHeader.split(":");
        headers[k.trim()] = rest.join(":").trim();
      }
      await addVendor({ name: vName.trim().toLowerCase(), url: vUrl.trim(), headers });
      setVName("");
      setVUrl("");
      setVHeader("");
      setShowVendorForm(false);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const submitAgent = async () => {
    setBusy(true);
    setError(null);
    try {
      const tools: Record<string, string[]> = {};
      if (narrowing) {
        for (const [vendor, set] of Object.entries(picked)) {
          if (set.size) tools[vendor] = [...set];
        }
      } else {
        for (const v of vendors.filter((x) => x.connected)) tools[v.name] = [ALL_TOOLS];
      }
      await addAgent({ id: id.trim().toLowerCase(), display_name: name.trim(), tools });
      setId("");
      setName("");
      setPicked({});
      setNarrowing(false);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const act = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const chosen = Object.values(picked).reduce((n, s) => n + s.size, 0);
  const connected = vendors.filter((v) => v.connected);
  const canAdd = id.trim() && (narrowing ? chosen > 0 : connected.length > 0);

  return (
    <>
      <Nav />
      <div className="shell">
        <h1>Connect</h1>

        {error && <div className="err">{error}</div>}

        {/* ------------------------------------------------------------ vendors */}

        <h2>Vendors</h2>
        <p className="lede">
          Any MCP server your agents call. Commons forwards to these and decides what gets
          through.
        </p>

        {vendors.length === 0 && !showVendorForm && (
          <div className="empty">None yet. Add the MCP server your agents talk to.</div>
        )}

        {vendors.map((v) => (
          <div className="vendor-row" key={v.name}>
            <div>
              <strong>{v.name}</strong>
              <div className="mono vendor-url">{v.url}</div>
              {!v.connected && <div className="reason">{v.error}</div>}
              {v.connected && !v.has_manifest && (
                <div className="reason">
                  No semantics manifest, so calls are forwarded and logged but no rule
                  applies to them.
                </div>
              )}
            </div>
            <div className="spacer" />
            <span className="verdict" data-v={v.connected ? "ALLOW" : "BLOCK"}>
              {v.connected ? `${(catalogue[v.name] ?? []).length} tools` : "down"}
            </span>
            <button className="btn btn-quiet" onClick={() => act(() => removeVendor(v.name))}>
              remove
            </button>
          </div>
        ))}

        {showVendorForm ? (
          <>
            <div className="agent-form">
              <label className="field">
                <span className="field-label">Name</span>
                <input
                  className="mono"
                  value={vName}
                  placeholder="my-crm"
                  onChange={(e) => setVName(e.target.value)}
                />
                <span className="field-hint">used in the URL</span>
              </label>
              <label className="field">
                <span className="field-label">MCP URL</span>
                <input
                  className="mono"
                  value={vUrl}
                  placeholder="https://mcp.example.com/mcp"
                  onChange={(e) => setVUrl(e.target.value)}
                />
              </label>
              <label className="field">
                <span className="field-label">Auth header</span>
                <input
                  className="mono"
                  value={vHeader}
                  placeholder="Authorization: Bearer env:MY_TOKEN"
                  onChange={(e) => setVHeader(e.target.value)}
                />
                <span className="field-hint">
                  optional. Most hosted servers want Bearer env:NAME, which reads the
                  token from .env instead of storing it here
                </span>
              </label>
            </div>
            <div className="review-actions">
              <button
                className="btn"
                disabled={!vName.trim() || !vUrl.trim() || busy}
                onClick={submitVendor}
              >
                {busy ? "connecting" : "Add vendor"}
              </button>
              <button className="btn btn-quiet" onClick={() => setShowVendorForm(false)}>
                cancel
              </button>
            </div>
          </>
        ) : (
          <div className="review-actions">
            <button className="btn btn-quiet" onClick={() => setShowVendorForm(true)}>
              add a vendor
            </button>
          </div>
        )}

        {/* ------------------------------------------------------------- agents */}

        <h2>Add an agent</h2>
        {vendors.filter((v) => v.connected).length === 0 ? (
          <div className="empty">Connect a vendor first.</div>
        ) : (
          <>
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
            </div>

            {narrowing &&
              connected.map((v) => (
                <section className="tool-picker" key={v.name}>
                  <div className="tool-picker-head">
                    <strong>{v.name}</strong>
                    <span className="field-hint">
                      pick only what this agent needs. {(picked[v.name]?.size ?? 0)} of{" "}
                      {(catalogue[v.name] ?? []).length} selected
                    </span>
                  </div>
                  <div className="tool-list">
                    {(catalogue[v.name] ?? []).map((t) => (
                      <label
                        className="tool"
                        key={t.name}
                        data-governed={t.governed}
                        title={t.description}
                      >
                        <input
                          type="checkbox"
                          checked={picked[v.name]?.has(t.name) ?? false}
                          onChange={() => toggle(v.name, t.name)}
                        />
                        <span className="mono">{t.name}</span>
                        {t.action_class && t.action_class !== "read" && (
                          <span className="tool-class">{t.action_class.replace(/_/g, " ")}</span>
                        )}
                      </label>
                    ))}
                  </div>
                </section>
              ))}

            {narrowing && (
              <p className="note">
                Highlighted tools are the ones Commons has semantics for, so rules can
                apply to them. The rest still work and are still logged.
              </p>
            )}

            <div className="review-actions">
              <button className="btn" disabled={!canAdd || busy} onClick={submitAgent}>
                {busy
                  ? "adding"
                  : narrowing
                    ? `Add agent with ${chosen} tools`
                    : "Add agent"}
              </button>
              <button className="btn btn-quiet" onClick={() => setNarrowing((n) => !n)}>
                {narrowing ? "use every tool instead" : "limit which tools it can call"}
              </button>
            </div>

            {!narrowing && (
              <p className="note">
                It gets every tool these vendors publish, which is what it has today
                without Commons. Every call is still governed: the rules are about what
                happens to a customer, not about which tool did it. Narrow it later from
                what it actually used.
              </p>
            )}
          </>
        )}

        {/* --------------------------------------------------------- registered */}

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
                      .map(([v, names]) =>
                        names.includes(ALL_TOOLS)
                          ? `${v}: all tools`
                          : `${v}: ${names.join(", ")}`
                      )
                      .join("   ·   ")}
                  </div>
                </div>
                <button className="btn btn-quiet" onClick={() => act(() => removeAgent(agent.id))}>
                  remove
                </button>
              </div>

              {/* Evidence, not a guess: what this agent has actually reached for. */}
              <div className="usage">
                {Object.entries(agent.used).length === 0 ? (
                  <span className="field-hint">no calls yet</span>
                ) : (
                  Object.entries(agent.used).map(([vendor, used]) => {
                    const total = (catalogue[vendor] ?? []).length;
                    const open = agent.tools[vendor]?.includes(ALL_TOOLS);
                    return (
                      <div key={vendor}>
                        <span className="field-hint">
                          {vendor}: used {used.length}
                          {total ? ` of ${total}` : ""} tools
                        </span>{" "}
                        <span className="mono usage-list">{used.join(", ")}</span>
                        {open && total > used.length && (
                          <button
                            className="btn btn-quiet"
                            onClick={() =>
                              act(() =>
                                addAgent({
                                  id: agent.id,
                                  display_name: agent.display_name,
                                  tools: { ...agent.tools, [vendor]: used },
                                })
                              )
                            }
                          >
                            narrow to these {used.length}
                          </button>
                        )}
                      </div>
                    );
                  })
                )}
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
            Paste that config into the agent, replacing the vendor URL it uses today.
          </li>
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
