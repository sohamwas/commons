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

            <h2>Step 1 — repoint each agent</h2>
            <p className="lede">
              This is the entire integration. Replace the vendor URL in the agent&apos;s MCP
              configuration with its Commons URL.
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
