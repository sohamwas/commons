"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { getHealth, type Health, type Mode } from "@/lib/api";

const PAGES = [
  { href: "/", label: "Customers" },
  { href: "/review", label: "Review" },
  { href: "/rules", label: "Rules" },
  { href: "/data", label: "Customer data" },
  { href: "/connect", label: "Connect" },
];

/**
 * Shared header.
 *
 * The mode switch lives here rather than on one page because it applies to the whole
 * gateway — and because a merchant needs to see, at all times, whether Commons is
 * currently watching or actually stopping things.
 */
export default function Nav({ onModeChange }: { onModeChange?: (m: Mode) => void }) {
  const pathname = usePathname();
  const [health, setHealth] = useState<Health | null>(null);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    let alive = true;
    const poll = () =>
      getHealth()
        .then((h) => {
          if (!alive) return;
          setHealth(h);
          setOffline(false);
        })
        .catch(() => alive && setOffline(true));
    poll();
    const timer = setInterval(poll, 5000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  return (
    <header className="top">
      <div className="top-inner">
        <Link href="/" className="wordmark" style={{ textDecoration: "none", color: "inherit" }}>
          Commons<span>arbitration gateway</span>
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
          <span className="pill pill-off" title="Start it with: python scripts/run_proxy.py">
            proxy offline
          </span>
        ) : (
          health && (
            <>
              <span className="pill" title={health.upstreams.join(", ")}>
                {health.upstreams.length} vendor
                {health.upstreams.length === 1 ? "" : "s"}
              </span>
              <span
                className="pill"
                data-mode={health.mode}
                title={
                  health.mode === "OBSERVE"
                    ? "Watching only — nothing is being stopped."
                    : "Policy is being enforced. Violating calls are stopped."
                }
              >
                {health.mode}
              </span>
            </>
          )
        )}
      </div>
    </header>
  );
}
