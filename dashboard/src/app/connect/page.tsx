"use client";

import { useEffect, useState } from "react";

import Nav from "@/components/Nav";
import { PROXY_URL, getHealth, type Health } from "@/lib/api";

/**
 * Onboarding.
 *
 * Adopting Commons is one line per agent: point it at a Commons URL instead of the
 * vendor's. Nothing inside the agent changes, which is the whole reason the proxy sits
 * where it does — it works for third-party agents whose code you cannot touch.
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
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch((e: Error) => setError(e.message));
  }, []);

  const byAgent = new Map<string, string[]>();
  for (const path of health?.endpoints ?? []) {
    const [, , agent] = path.split("/");
    byAgent.set(agent, [...(byAgent.get(agent) ?? []), path]);
  }

  return (
    <>
      <Nav />
      <div className="shell">
        <h1>Connect your agents</h1>
        <p className="lede">
          Each agent gets its own Commons address. Point it there instead of at the
          vendor, and every call it makes becomes visible to policy that spans your whole
          fleet. You do not modify the agent — which is why this works for agents you did
          not build.
        </p>

        {error && (
          <div className="err">
            {error}
            <div style={{ marginTop: 10, color: "var(--text-dim)" }}>
              Commons is not running. Start it from the repo you cloned:
              <pre className="mono" style={{ marginTop: 8 }}>
                python scripts/run_proxy.py
              </pre>
            </div>
          </div>
        )}

        {health && (
          <>
            <div className="ok-banner">
              Commons is running at <span className="mono">{PROXY_URL}</span> — connected
              to {health.upstreams.join(" and ")}, {health.rules.length} rules loaded.
            </div>

            <h2>What Commons can and cannot sit in front of</h2>
            <div className="ledger" style={{ marginBottom: 8 }}>
              <table>
                <thead>
                  <tr>
                    <th style={{ width: 300 }}>Agent</th>
                    <th style={{ width: 110 }}>Works today</th>
                    <th>Why</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>Agents you run yourself — your own code, Claude Desktop, Cursor,
                      VS Code, n8n, LangChain</td>
                    <td className="verdict" data-v="ALLOW">YES</td>
                    <td style={{ color: "var(--text-dim)" }}>
                      You control the MCP config, so you can point it anywhere.
                    </td>
                  </tr>
                  <tr>
                    <td>A third-party agent you deploy and configure</td>
                    <td className="verdict" data-v="ALLOW">YES</td>
                    <td style={{ color: "var(--text-dim)" }}>
                      Commons needs its tool schema, not its source.
                    </td>
                  </tr>
                  <tr data-violation="true">
                    <td>Razorpay Agent Studio agents</td>
                    <td className="verdict" data-v="BLOCK">NOT YET</td>
                    <td style={{ color: "var(--text-dim)" }}>
                      They run on Razorpay&apos;s infrastructure and expose no
                      merchant-configurable MCP endpoint. See below.
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div className="warn">
              <strong>Agent Studio agents cannot be routed through Commons today</strong>,
              and it is worth being precise about why — there are two separate blockers.
              <br />
              <br />
              <strong>1. Reachability.</strong> Those agents execute on Razorpay&apos;s
              servers. Commons runs on your machine at{" "}
              <span className="mono">127.0.0.1</span>, which Razorpay cannot reach. A
              tunnel (ngrok, Cloudflare Tunnel) solves this half — but it means exposing a
              gateway that sees your payment traffic to the public internet, so it is a
              decision to make deliberately rather than a default.
              <br />
              <br />
              <strong>2. Configurability, which is the real blocker.</strong> Agent Studio
              is a managed marketplace. It does not let a merchant change where an agent
              sends its tool calls, so even a publicly reachable Commons has nothing to
              point at it. A tunnel does not fix this.
              <br />
              <br />
              This is not a gap in Commons so much as the gap Commons exists to describe.
              Razorpay has said third-party builders{" "}
              <em>will be able to</em> publish agents to Agent Studio. At that point a
              merchant will be running agents from several parties at once, and the
              question of who enforces limits across all of them becomes unavoidable — it
              needs either a merchant-configurable endpoint, or this arbitration built into
              the platform itself.
            </div>

            <h2>Step 1 — repoint each agent</h2>
            <p className="lede">
              For every agent you control, this is the entire integration: replace the
              vendor URL in its MCP configuration with its Commons URL. Nothing inside the
              agent changes, which is why it works for agents you did not write.
            </p>

            {[...byAgent.entries()].map(([agent, paths]) => (
              <section className="rule" key={agent}>
                <div className="rule-head">
                  <strong>{agent.replace(/-/g, " ")}</strong>
                </div>
                {paths.map((path) => {
                  const upstream = path.split("/")[3];
                  return (
                    <div key={path} style={{ marginBottom: 12 }}>
                      <div className="field-label" style={{ marginBottom: 6 }}>
                        {upstream}
                      </div>
                      <Copyable
                        text={JSON.stringify(
                          {
                            mcpServers: {
                              [upstream]: { url: `${PROXY_URL}${path}` },
                            },
                          },
                          null,
                          2
                        )}
                      />
                    </div>
                  );
                })}
              </section>
            ))}

            <h2>Step 2 — check it is reaching Commons</h2>
            <p className="lede">
              Once an agent is repointed, its calls appear on the Customers page. If
              nothing shows up, the agent is still talking to the vendor directly.
            </p>
            <Copyable text={`curl ${PROXY_URL}/health`} />

            <h2>Step 3 — tell Commons who your customers are</h2>
            <p className="lede">
              Commons never guesses that a phone number and an email belong to the same
              person. Import your customer list on the{" "}
              <a href="/data">Customer data</a> page so calls from different vendors
              resolve to one human.
            </p>

            <h2>Step 4 — watch before you enforce</h2>
            <p className="lede">
              Leave Commons in OBSERVE. Nothing is blocked, so no agent can break. After a
              few days, work through the <a href="/review">Review</a> queue and confirm
              whether each flagged call should have been stopped. Then switch on
              enforcement from the <a href="/rules">Rules</a> page.
            </p>

            <p className="note">
              Commons runs entirely on your machine. It sees payment amounts, customer
              identifiers and refund decisions, so it is never hosted for you — nothing
              here leaves your network except the calls your agents were already making to
              their vendors.
            </p>
          </>
        )}
      </div>
    </>
  );
}
