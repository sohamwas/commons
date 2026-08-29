/**
 * Client for the merchant's own Commons proxy.
 *
 * The dashboard is a LOCAL application: the merchant clones the repo, runs the proxy on
 * their own machine, and this talks to it. Commons sees payment amounts, customer
 * identifiers and refund decisions, so nothing here should ever point at someone else's
 * server. That is why the base URL defaults to loopback and is overridable only by the
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

export interface Vendor {
  name: string;
  url: string;
  auth: string | null;
  connected: boolean;
  error: string | null;
  has_manifest: boolean;
}

export interface VendorTool {
  name: string;
  description: string;
  /** Commons knows what this tool does and to whom, so rules can apply to it. */
  governed: boolean;
  action_class: string | null;
}

export interface Agent {
  id: string;
  display_name: string;
  /** A vendor mapped to ["*"] means every tool that vendor publishes. */
  tools: Record<string, string[]>;
  /** Tools this agent has actually called, per vendor. */
  used: Record<string, string[]>;
  endpoints: string[];
}

/** Every tool the vendor publishes. */
export const ALL_TOOLS = "*";

export interface Health {
  service: string;
  version: string;
  mode: Mode;
  run_id: string | null;
  upstreams: string[];
  manifests: Record<string, number>;
  rules: string[];
  endpoints: string[];
  agents: string[];
  /** Vendors that did not connect, mapped to why. */
  unavailable: Record<string, string>;
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

export const getVendors = () => call<{ vendors: Vendor[] }>("/admin/vendors");

export const addVendor = (body: {
  name: string;
  url: string;
  headers?: Record<string, string>;
  auth?: string;
}) => call<{ name: string }>("/admin/vendors", { method: "POST", body: JSON.stringify(body) });

export const removeVendor = (name: string) =>
  call<{ removed: string }>(`/admin/vendors/${encodeURIComponent(name)}`, {
    method: "DELETE",
  });

/** What a vendor publishes, so nobody has to remember tool names. */
export const getVendorTools = (name: string) =>
  call<{ vendor: string; has_manifest: boolean; tools: VendorTool[] }>(
    `/admin/vendors/${encodeURIComponent(name)}/tools`
  );

export const getAgents = () =>
  call<{ agents: Agent[]; vendors: string[] }>("/admin/agents");

/** Register an agent. It is served immediately, with no restart. */
export const addAgent = (body: {
  id: string;
  display_name?: string;
  tools: Record<string, string[]>;
}) =>
  call<{ id: string; endpoints: string[] }>("/admin/agents", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const removeAgent = (id: string) =>
  call<{ removed: string }>(`/admin/agents/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });

export interface SyncResult {
  source: string;
  found: number;
  imported: number;
  dry_run: boolean;
  warnings: string[];
  preview: Array<{ display_name: string; handles: Record<string, string> }>;
}

/** Pull customers from a vendor the merchant already uses. */
export const syncCustomers = (body: { source?: string; limit?: number; dry_run?: boolean }) =>
  call<SyncResult>("/api/sync", { method: "POST", body: JSON.stringify(body) });

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

// ---------------------------------------------------------------- csv

/**
 * Split CSV text into rows.
 *
 * Written out rather than split on commas because these are real exports: a CRM will
 * happily emit `"Rao, Arjun"`, and Excel writes a BOM that would otherwise become part of
 * the first column name.
 */
function parseCsv(text: string): string[][] {
  if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);

  const rows: string[][] = [];
  let row: string[] = [];
  let cur = "";
  let quoted = false;

  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch !== '"') cur += ch;
      else if (text[i + 1] === '"') (cur += '"'), i++;
      else quoted = false;
      continue;
    }
    if (ch === '"') quoted = true;
    else if (ch === ",") (row.push(cur), (cur = ""));
    else if (ch === "\n") (row.push(cur), rows.push(row), (row = []), (cur = ""));
    else if (ch !== "\r") cur += ch;
  }
  if (cur !== "" || row.length) (row.push(cur), rows.push(row));

  return rows.filter((r) => r.some((c) => c.trim() !== ""));
}

/** Header spellings seen in real exports, mapped to the handle namespaces Commons uses. */
const COLUMNS: Record<string, string> = {
  "customer id": "customer_id",
  customerid: "customer_id",
  customer_id: "customer_id",
  id: "customer_id",
  name: "name",
  "full name": "name",
  "customer name": "name",
  fullname: "name",
  phone: "phone",
  contact: "phone",
  mobile: "phone",
  "phone number": "phone",
  phone_number: "phone",
  "contact number": "phone",
  "mobile number": "phone",
  email: "email",
  "email address": "email",
  email_address: "email",
  "e-mail": "email",
  "order id": "order_id",
  order_id: "order_id",
  orderid: "order_id",
  order: "order_id",
};

export interface CsvImport {
  entities: Array<{ ref?: string; display_name: string; handles: Record<string, string> }>;
  used: string[];
  ignored: string[];
}

/** Turn a customer export into the declare payload. */
export function readCustomerCsv(text: string): CsvImport {
  const rows = parseCsv(text);
  if (rows.length === 0) return { entities: [], used: [], ignored: [] };

  const header = rows[0].map((h) => h.trim().toLowerCase());
  const cols = header.map((h) => COLUMNS[h] ?? null);

  const used = header.filter((_, i) => cols[i]);
  const ignored = header.filter((h, i) => !cols[i] && h !== "");

  const entities = rows.slice(1).map((cells) => {
    const handles: Record<string, string> = {};
    let display = "";
    cols.forEach((col, i) => {
      const value = (cells[i] ?? "").trim();
      if (!col || !value) return;
      if (col === "name") display = value;
      else handles[col] = value;
    });
    return {
      ref: handles.customer_id,
      display_name: display || handles.customer_id || handles.phone || handles.email || "",
      handles,
    };
  });

  // A row with no handle at all cannot be declared, so drop it rather than send it.
  return { entities: entities.filter((e) => Object.keys(e.handles).length > 0), used, ignored };
}
