"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { getHealth, updatePolicy, type Health } from "@/lib/api";

const PAGES = [
  { href: "/", label: "Customers" },
  { href: "/review", label: "Review" },
  { href: "/rules", label: "Rules" },
  { href: "/data", label: "Data" },
  { href: "/connect", label: "Connect" },
];

/**
 * Shared header.
 *
 * Mode is a control here, not a readout. It applies to the whole gateway, and a merchant
 * needs to know at all times whether Commons is watching or actually stopping things, so
 * burying the switch on one page made it easy to misread every other page.
 */
export default function Nav() {
  const pathname = usePathname();
  const [health, setHealth] = useState<Health | null>(null);
  const [offline, setOffline] = useState(false);

  const poll = useCallback(
    () =>
      getHealth()
        .then((h) => {
          setHealth(h);
          setOffline(false);
        })
        .catch(() => setOffline(true)),
    []
  );

  useEffect(() => {
    poll();
    const timer = setInterval(poll, 5000);
    return () => clearInterval(timer);
  }, [poll]);

  const toggleMode = async () => {
    if (!health) return;
    const next = health.mode === "OBSERVE" ? "ENFORCE" : "OBSERVE";
    setHealth({ ...health, mode: next });
    try {
      await updatePolicy({ mode: next });
    } catch {
      poll(); // the gateway is the authority, so fall back to what it reports
    }
  };

  return (
    <header className="top">
      <div className="top-inner">
        <Link href="/" className="wordmark">
          Commons
        </Link>

        <nav className="nav">
          {PAGES.map((p) => (
            <Link
              key={p.href}
              href={p.href}
              data-active={pathname === p.href}
              className="nav-link"
            >
              {p.label}
            </Link>
          ))}
        </nav>

        <div className="spacer" />

        {offline ? (
          <span className="pill pill-off" title="python scripts/run_proxy.py">
            offline
          </span>
        ) : (
          health && (
            <button
              className="pill"
              data-mode={health.mode}
              onClick={toggleMode}
              title={
                health.mode === "OBSERVE"
                  ? "Watching only. Click to enforce."
                  : "Violating calls are stopped. Click to observe."
              }
            >
              {health.mode}
            </button>
          )
        )}
      </div>
    </header>
  );
}
