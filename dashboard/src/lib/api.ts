/**
 * Client for the merchant's own Commons proxy.
 *
 * The dashboard is a LOCAL application: the merchant clones the repo, runs the proxy on
 * their own machine, and this talks to it. Commons sees payment amounts, customer
 * identifiers and refund decisions, so nothing here should ever point at someone else's
 * server — which is why the base URL defaults to loopback and is overridable only by the
 * person running it.
 */

export const PROXY_URL =
  process.env.NEXT_PUBLIC_COMMONS_URL ?? "http://127.0.0.1:8787";

export class ProxyDown extends Error {
  constructor(cause: string) {
    super(
      `Cannot reach Commons at ${PROXY_URL}. Start it with: python scripts/run_proxy.py  (${cause})`
    );
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${PROXY_URL}${path}`, {
      ...init,
      cache: "no-store",
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch (e) {
    throw new ProxyDown(e instanceof Error ? e.message : "network error");
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error((body as { error?: string }).error ?? `${res.status} ${res.statusText}`);
  }
  return body as T;
}

// ---------------------------------------------------------------- types

export type Mode = "OBSERVE" | "ENFORCE";
export type ReviewVerdict = "correct" | "incorrect" | "unsure";

export interface PolicyRule {
  id: string;
  english: string;
  primitive: string;
  on_violation: "BLOCK" | "DEFER";
  scope: Record<string, unknown>;
  enabled: boolean;
  compiled: string;
  english_mismatch: string | null;
}

export interface Policy {
  mode: Mode;
  rules: PolicyRule[];
}

export interface Health {
  service: string;
  version: string;
  mode: Mode;
  run_id: string | null;
  upstreams: string[];
  manifests: Record<string, number>;
  rules: string[];
  endpoints: string[];
}

export interface AdminEntity {
  id: string;
  display_name: string;
  handles: [string, string][];
  state: Record<string, string>;
}

// ---------------------------------------------------------------- calls

export const getHealth = () => call<Health>("/health");
export const getPolicy = () => call<Policy>("/api/policy");

export const updatePolicy = (body: {
  mode?: Mode;
  rules?: Array<Partial<PolicyRule> & { id: string }>;
}) => call<Policy>("/api/policy", { method: "PUT", body: JSON.stringify(body) });

export const submitReview = (body: {
  call_id: number;
  rule_id: string;
  verdict: ReviewVerdict;
  note?: string;
}) => call<{ ok: boolean }>("/api/review", { method: "POST", body: JSON.stringify(body) });

export const getEntities = () => call<AdminEntity[]>("/admin/entities");

export const declareEntities = (
  entities: Array<{
    ref?: string;
    display_name?: string;
    handles: Record<string, string>;
    state?: Record<string, string>;
  }>
) =>
  call<{ seeded: number; entities: Record<string, string> }>("/admin/entities", {
    method: "POST",
    body: JSON.stringify({ entities }),
  });

/** Parse a pasted CSV of customers into the declare payload. */
export function parseCustomerCsv(text: string) {
  const lines = text.trim().split(/\r?\n/).filter(Boolean);
  if (lines.length === 0) return [];
  const header = lines[0].split(",").map((h) => h.trim().toLowerCase());
  const known = ["customer_id", "name", "phone", "email", "order_id"];
  const cols = header.map((h) => (known.includes(h) ? h : null));

  return lines.slice(1).map((line) => {
    const cells = line.split(",").map((c) => c.trim());
    const handles: Record<string, string> = {};
    let display = "";
    cols.forEach((col, i) => {
      const value = cells[i];
      if (!col || !value) return;
      if (col === "name") display = value;
      else handles[col] = value;
    });
    return {
      ref: handles.customer_id,
      display_name: display || handles.customer_id || handles.phone,
      handles,
    };
  });
}
