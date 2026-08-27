"use client";

import { useEffect, useState } from "react";

import Nav from "@/components/Nav";
import { PROXY_URL, getHealth, type Health } from "@/lib/api";

/**
 * Onboarding.
 *
 * Adoption is one line per agent: point it at a Commons URL instead of the vendor's.
 * Nothing inside the agent changes, which is the whole reason the proxy sits where it
 * does. It works for third-party agents whose source you cannot touch.
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

const WORKS: [string, boolean, string][] = [
  ["Your own code", true, "You own the MCP config"],
  ["Claude Desktop, Cursor, VS Code", true, "You own the MCP config"],
  ["n8n, LangChain, CrewAI, Zapier", true, "All take an MCP URL"],
  ["Third-party agents you deploy", true, "Commons needs the tool schema, not the source"],
  ["Razorpay Agent Studio", false, "Managed. No merchant-configurable endpoint."],
];

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
        <h1>Connect</h1>
        <p className="lede">
          Replace the vendor URL in an agent&apos;s MCP config with its Commons URL. That is
          the whole integration.
        </p>

        {error && (
          <div className="err">
            {error}
            <div className="mono">python scripts/run_proxy.py</div>
          </div>
        )}

        {health && (
          <>
            <div className="ok-banner">
              <span className="mono">{PROXY_URL}</span> · {health.upstreams.join(", ")} ·{" "}
              {health.rules.length} rules
            </div>

            <h2>What Commons can sit in front of</h2>
            <div className="ledger">
              <table>
                <tbody>
                  {WORKS.map(([what, ok, why]) => (
                    <tr key={what} data-violation={!ok}>
                      <td style={{ width: 300 }}>{what}</td>
                      <td style={{ width: 70 }}>
                        <span className="verdict" data-v={ok ? "ALLOW" : "BLOCK"}>
                          {ok ? "yes" : "no"}
                        </span>
                      </td>
                      <td style={{ color: "var(--text-dim)" }}>{why}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <h2>Endpoints</h2>
            {[...byAgent.entries()].map(([agent, paths]) => (
              <section className="rule" key={agent}>
                <div className="rule-head">
                  <strong>{agent.replace(/-/g, " ")}</strong>
                </div>
                {paths.map((path) => {
                  const upstream = path.split("/")[3];
                  return (
                    <Copyable
                      key={path}
                      text={JSON.stringify(
                        { mcpServers: { [upstream]: { url: `${PROXY_URL}${path}` } } },
                        null,
                        2
                      )}
                    />
                  );
                })}
              </section>
            ))}

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
                Stay in OBSERVE. Work through <a href="/review">Review</a>, then enforce from{" "}
                <a href="/rules">Rules</a>.
              </li>
            </ol>

            <h2>Agent Studio</h2>
            <p className="lede">
              Agent Studio runs agents on Razorpay&apos;s infrastructure and exposes no way
              for a merchant to change where an agent sends its tool calls. A tunnel would
              fix reachability but not that.
            </p>
            <p className="lede">
              This is the gap Commons exists to describe. Once third-party builders publish
              there, a merchant runs agents from several parties against the same customers,
              and no vendor can see what the others did. That needs either a
              merchant-configurable endpoint or this arbitration in the platform.
            </p>

            <p className="note">
              Commons runs on your machine. Nothing leaves your network except the calls your
              agents were already making.
            </p>
          </>
        )}
      </div>
    </>
  );
}
