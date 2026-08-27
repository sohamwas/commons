import type { RunData } from "./types";

/**
 * One adapter, two backends.
 *
 *   file:  a recorded run committed to the repo   -> the hosted demo, no backend at all
 *   http:  a live Commons proxy                   -> the local app, watching a real run
 *
 * Both return the identical shape, so every component below is written once and never
 * learns which it is looking at. That is what makes the free hosted replay possible: the
 * determinism built for the A/B comparison pays for itself twice (handoff §15.3).
 */

export type SourceKind = "file" | "http";

export interface Source {
  kind: SourceKind;
  label: string;
  url: string;
}

export const RECORDED_RUNS: Record<string, Source> = {
  observe: {
    kind: "file",
    label: "OBSERVE recorded run, seed 4471",
    url: "runs/observe-4471.json",
  },
  enforce: {
    kind: "file",
    label: "ENFORCE recorded run, seed 4471",
    url: "runs/enforce-4471.json",
  },
};

export const LIVE_SOURCE: Source = {
  kind: "http",
  label: "LIVE local Commons proxy",
  url: "http://127.0.0.1:8787/api/run",
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
