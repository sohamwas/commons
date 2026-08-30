"use client";

import { useEffect, useState } from "react";

import Nav from "@/components/Nav";
import {
  getPolicy,
  updatePolicy,
  type Mode,
  type Policy,
  type PolicyRule,
} from "@/lib/api";

/**
 * The merchant's policy, editable.
 *
 * 15% was our demo's number, not everyone's. Each rule shows the plain-English sentence
 * beside the invariant actually enforced, and warns when the two have
 * drifted apart: a screen stating one number while the gateway enforces another is worse
 * than either being wrong.
 */

// Which scope keys are safely editable, and how to present them.
const FIELDS: Record<string, { label: string; hint: string; kind: "number" | "duration" }> = {
  cap: { label: "Cap", hint: "", kind: "number" },
  max: { label: "Max", hint: "", kind: "number" },
  window: { label: "Window", hint: "24h, 30d", kind: "duration" },
  lease: { label: "Lease", hint: "30m", kind: "duration" },
};

export default function RulesPage() {
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [draft, setDraft] = useState<Record<string, Partial<PolicyRule>>>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);

  const load = () =>
    getPolicy()
      .then((p) => {
        setPolicy(p);
        setDraft({});
        setError(null);
      })
      .catch((e: Error) => setError(e.message));

  useEffect(() => {
    load();
  }, []);

  const edit = (id: string, patch: Partial<PolicyRule>) =>
    setDraft((d) => ({ ...d, [id]: { ...d[id], ...patch } }));

  const editScope = (id: string, key: string, value: unknown) =>
    setDraft((d) => ({
      ...d,
      [id]: { ...d[id], scope: { ...(d[id]?.scope ?? {}), [key]: value } },
    }));

  const save = async (id: string) => {
    const patch = draft[id];
    if (!patch) return;
    setSaving(true);
    try {
      const next = await updatePolicy({ rules: [{ ...patch, id }] });
      setPolicy(next);
      setDraft((d) => {
        const { [id]: _drop, ...rest } = d;
        return rest;
      });
      setSaved(id);
      setTimeout(() => setSaved(null), 2500);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const setMode = async (mode: Mode) => {
    try {
      setPolicy(await updatePolicy({ mode }));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <>
      <Nav />
      <div className="shell">
        <h1>Rules</h1>

        {error && <div className="err">{error}</div>}
        {!policy && !error && <div className="loading">loading</div>}

        {policy && (
          <>
            <div className="mode-card">
              <div>
                <div className="mode-title">{policy.mode}</div>
                <div className="mode-sub">
                  {policy.mode === "OBSERVE"
                    ? "Recording violations. Nothing is stopped."
                    : "Violating calls are stopped before the vendor."}
                </div>
              </div>
              <div className="spacer" />
              <div className="modes">
                {(["OBSERVE", "ENFORCE"] as const).map((m) => (
                  <button
                    key={m}
                    data-mode={m}
                    data-active={policy.mode === m}
                    onClick={() => setMode(m)}
                  >
                    {m}
                  </button>
                ))}
              </div>
            </div>

            {policy.rules.map((rule) => {
              const patch = draft[rule.id] ?? {};
              const dirty = Object.keys(patch).length > 0;
              const scope = { ...rule.scope, ...(patch.scope ?? {}) };
              const enabled = patch.enabled ?? rule.enabled;

              return (
                <section className="rule" key={rule.id} data-off={!enabled}>
                  <div className="rule-head">
                    <div style={{ flex: 1 }}>
                      <input
                        className="rule-english"
                        value={patch.english ?? rule.english}
                        onChange={(e) => edit(rule.id, { english: e.target.value })}
                        aria-label={`${rule.id} description`}
                      />
                      <div className="rule-compiled mono">
                        {rule.primitive} · {rule.id}
                        {(scope.action_class as string[] | undefined) && (
                          <> · {(scope.action_class as string[]).join(", ")}</>
                        )}
                      </div>
                    </div>
                    <label className="toggle" title="Turn off without deleting">
                      <input
                        type="checkbox"
                        checked={enabled}
                        onChange={(e) => edit(rule.id, { enabled: e.target.checked })}
                      />
                      <span>{enabled ? "on" : "off"}</span>
                    </label>
                  </div>

                  {rule.english_mismatch && (
                    <div className="warn">
                      Sentence and enforced limit disagree: {rule.english_mismatch}.
                    </div>
                  )}

                  <div className="rule-fields">
                    {Object.entries(FIELDS).map(([key, meta]) =>
                      key in rule.scope ? (
                        <label className="field" key={key}>
                          <span className="field-label">{meta.label}</span>
                          <input
                            className="mono"
                            value={String(scope[key] ?? "")}
                            onChange={(e) =>
                              editScope(
                                rule.id,
                                key,
                                meta.kind === "number"
                                  ? Number(e.target.value) || 0
                                  : e.target.value
                              )
                            }
                          />
                          {meta.hint && <span className="field-hint">{meta.hint}</span>}
                        </label>
                      ) : null
                    )}

                    <label className="field">
                      <span className="field-label">Breach</span>
                      <select
                        className="mono"
                        value={patch.on_violation ?? rule.on_violation}
                        onChange={(e) =>
                          edit(rule.id, {
                            on_violation: e.target.value as "BLOCK" | "DEFER",
                          })
                        }
                      >
                        <option value="BLOCK">BLOCK</option>
                        <option value="DEFER">DEFER</option>
                      </select>
                      <span className="field-hint">ENFORCE only</span>
                    </label>
                  </div>

                  <div className="rule-foot">
                    <button
                      className="btn"
                      disabled={!dirty || saving}
                      onClick={() => save(rule.id)}
                    >
                      {saving ? "saving" : "Save"}
                    </button>
                    {dirty && (
                      <button
                        className="btn btn-quiet"
                        onClick={() =>
                          setDraft((d) => {
                            const { [rule.id]: _drop, ...rest } = d;
                            return rest;
                          })
                        }
                      >
                        Discard
                      </button>
                    )}
                    {saved === rule.id && <span className="ok">saved</span>}
                  </div>
                </section>
              );
            })}

            <p className="note">Live on the next tool call. Nothing to restart.</p>
          </>
        )}
      </div>
    </>
  );
}
