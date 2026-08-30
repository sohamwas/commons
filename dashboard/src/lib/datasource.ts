import { PROXY_URL } from "./api";
import type { RunData } from "./types";

/**
 * Where the dashboard gets a run from.
 *
 * One source today: the merchant's own Commons proxy. The shape is a single
 * self-contained JSON document, so a component never learns where it came from and a
 * second source could be added without touching any of them.
 */

export interface Source {
  label: string;
  url: string;
}

// Same base URL the rest of the client uses. It was hardcoded here while api.ts read
// NEXT_PUBLIC_COMMONS_URL, so pointing the dashboard at a proxy on another port moved
// every write but left the run feed talking to 8787.
export const LIVE_SOURCE: Source = {
  label: "LIVE local Commons proxy",
  url: `${PROXY_URL}/api/run`,
};

export async function loadRun(source: Source): Promise<RunData> {
  const res = await fetch(source.url, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`${source.label}: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as RunData;
}

// ---------------------------------------------------------------- helpers

export function agentName(agents: { id: string; display_name: string }[], id: string) {
  return agents.find((a) => a.id === id)?.display_name ?? id;
}

export function handleOf(entity: { handles: [string, string][] }, namespace: string) {
  return entity.handles.find(([ns]) => ns === namespace)?.[1];
}

/** Mask a phone number the way a support console would. */
export function maskPhone(phone?: string) {
  if (!phone) return "";
  return phone.length > 6 ? `${phone.slice(0, 5)}•••••${phone.slice(-2)}` : phone;
}

export function formatDay(iso: string) {
  return new Date(iso).toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
}

export function formatTime(iso: string) {
  return new Date(iso).toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

/**
 * Lane colour for an agent.
 *
 * The four demo agents have named colours. Anything else, including an agent a merchant
 * registered themselves, cycles a palette by position, so a fifth agent gets a real lane
 * instead of falling back to the same grey as every other unknown one.
 */
const NAMED: Record<string, string> = {
  "cart-recovery": "var(--agent-cart)",
  "subscription-recovery": "var(--agent-subscription)",
  "dispute-responder": "var(--agent-dispute)",
  "rto-shield": "var(--agent-rto)",
};

const PALETTE = ["#b07cd6", "#e07a5f", "#5fa8d3", "#84a98c", "#d4a373"];

export function laneColor(agentId: string, index = 0): string {
  return NAMED[agentId] ?? PALETTE[index % PALETTE.length];
}
