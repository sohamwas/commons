"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { getHealth, type Health, type Mode } from "@/lib/api";

const PAGES = [
  { href: "/", label: "Customers" },
  { href: "/review", label: "Review" },
  { href: "/rules", label: "Rules" },
  { href: "/data", label: "Data" },
  { href: "/connect", label: "Connect" },
];

/** Shared header. Mode lives here because it applies to the whole gateway. */
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
            <>
              <span className="pill" title={health.upstreams.join(", ")}>
                {health.upstreams.length} vendors
              </span>
              <span
                className="pill"
                data-mode={health.mode}
                title={
                  health.mode === "OBSERVE"
                    ? "Watching only. Nothing is stopped."
                    : "Violating calls are stopped."
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
