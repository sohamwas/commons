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
 *
 * The agent names below come from /health, so this page describes whatever the merchant
 * has registered rather than the cast this project happened to demo with.
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

const REGISTER_EXAMPLE = `# commons/proxy/registry.py
AGENTS = {
    "my-agent": AgentSpec(
        id="my-agent",
        display_name="My Agent",
        tools={
            "razorpay": ("create_payment_link", "fetch_order"),
            "messaging": ("send_whatsapp",),
        },
    ),
}`;

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
          Replace the vendor URL in an agent&apos;s MCP config with its Commons URL.
        </p>

        {error && (
          <div className="err">
            {error}
            <div className="mono">python scripts/run_proxy.py</div>
          </div>
        )}

        {health && (
          <>
            <h2>URL pattern</h2>
            <Copyable text={`${PROXY_URL}/mcp/{agent}/{vendor}`} />
            <p className="note">
              <span className="mono">{"{agent}"}</span> is any agent you register.{" "}
              <span className="mono">{"{vendor}"}</span> is one of{" "}
              <span className="mono">{health.upstreams.join(", ")}</span>. Each agent gets
              its own address so Commons knows who is calling.
            </p>

            <h2>Registered agents</h2>
            {[...byAgent.entries()].map(([agent, paths]) => (
              <section className="rule" key={agent}>
                <div className="rule-head">
                  <strong>{agent}</strong>
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

            <h2>Register your own</h2>
            <Copyable text={REGISTER_EXAMPLE} />
            <p className="note">
              An agent needs an id and the tools it may call on each vendor. Restart Commons
              after editing, and its addresses appear above.
            </p>

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
                ENFORCE.
              </li>
            </ol>

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
