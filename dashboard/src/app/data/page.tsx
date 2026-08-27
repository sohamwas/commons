"use client";

import { useEffect, useState } from "react";

import Nav from "@/components/Nav";
import {
  declareEntities,
  getEntities,
  parseCustomerCsv,
  syncCustomers,
  type AdminEntity,
  type SyncResult,
} from "@/lib/api";

/**
 * Customer data sync.
 *
 * This is what makes cross-vendor policy possible at all. Normalisation unifies different
 * spellings of the SAME detail; it cannot know that a phone number and an email belong to
 * one person. Commons refuses to guess at that, because in a system that can block a
 * payment a wrong merge is far worse than no merge. The merchant states it, once, from the
 * customer list they already have.
 */

const SAMPLE = `customer_id,name,phone,email,order_id
cust_1001,Priya Sharma,+919800000021,priya@example.com,order_1001
cust_1002,Arjun Rao,9800000022,arjun@example.com,order_1002`;

export default function DataPage() {
  const [entities, setEntities] = useState<AdminEntity[] | null>(null);
  const [csv, setCsv] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sync, setSync] = useState<SyncResult | null>(null);
  const [syncing, setSyncing] = useState(false);

  const load = () =>
    getEntities()
      .then((e) => {
        setEntities(e);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));

  const runSync = async (dryRun: boolean) => {
    setSyncing(true);
    setError(null);
    try {
      const res = await syncCustomers({ source: "razorpay", limit: 100, dry_run: dryRun });
      setSync(res);
      if (!dryRun) await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSyncing(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const preview = csv.trim() ? parseCustomerCsv(csv) : [];

  const submit = async () => {
    setBusy(true);
    setResult(null);
    try {
      const res = await declareEntities(preview);
      setResult(`Imported ${res.seeded}`);
      setCsv("");
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Nav />
      <div className="shell">
        <h1>Customer data</h1>
        <p className="lede">
          Commons unifies one detail written many ways. It never guesses that a phone and an
          email are the same person, so tell it once.
        </p>

        {error && <div className="err">{error}</div>}

        <h2>Sync from Razorpay</h2>
        <div className="review-actions">
          <button className="btn" disabled={syncing} onClick={() => runSync(true)}>
            {syncing ? "checking" : "Preview"}
          </button>
          {sync && sync.dry_run && sync.found > 0 && (
            <button className="btn" disabled={syncing} onClick={() => runSync(false)}>
              Import {sync.found}
            </button>
          )}
        </div>

        {sync && (
          <>
            <div className={sync.found ? "ok-banner" : "warn"}>
              {sync.dry_run ? `Found ${sync.found}` : `Imported ${sync.imported}`}
            </div>
            {sync.warnings.map((w, i) => (
              <div className="warn" key={i}>
                {w}
              </div>
            ))}
            {sync.preview.length > 0 && (
              <div className="ledger">
                <table>
                  <thead>
                    <tr>
                      <th style={{ width: 220 }}>Customer</th>
                      <th>Handles</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sync.preview.map((p, i) => (
                      <tr key={i}>
                        <td>{p.display_name}</td>
                        <td className="mono" style={{ color: "var(--text-dim)" }}>
                          {Object.entries(p.handles)
                            .map(([k, v]) => `${k}=${v}`)
                            .join("  ·  ")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}

        <h2>Import CSV</h2>
        <p className="lede">
          Columns: <span className="mono">customer_id, name, phone, email, order_id</span>.
          Only the ones you have.
        </p>

        <textarea
          className="csv"
          value={csv}
          placeholder={SAMPLE}
          onChange={(e) => setCsv(e.target.value)}
          spellCheck={false}
        />

        <div className="review-actions">
          <button className="btn" disabled={!preview.length || busy} onClick={submit}>
            {busy ? "importing" : `Import ${preview.length || ""}`}
          </button>
          <button className="btn btn-quiet" onClick={() => setCsv(SAMPLE)}>
            example
          </button>
          {result && <span className="ok">{result}</span>}
        </div>

        {preview.length > 0 && (
          <div className="ledger">
            <table>
              <thead>
                <tr>
                  <th style={{ width: 220 }}>Name</th>
                  <th>Handles</th>
                </tr>
              </thead>
              <tbody>
                {preview.slice(0, 8).map((p, i) => (
                  <tr key={i}>
                    <td>{p.display_name}</td>
                    <td className="mono" style={{ color: "var(--text-dim)" }}>
                      {Object.entries(p.handles)
                        .map(([k, v]) => `${k}=${v}`)
                        .join("  ·  ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <h2>Known ({entities?.length ?? 0})</h2>
        {!entities && !error && <div className="loading">loading</div>}
        {entities && entities.length === 0 && <div className="empty">None yet.</div>}
        {entities && entities.length > 0 && (
          <div className="ledger">
            <table>
              <thead>
                <tr>
                  <th style={{ width: 200 }}>Customer</th>
                  <th>Known by</th>
                  <th style={{ width: 150 }}>State</th>
                </tr>
              </thead>
              <tbody>
                {entities.slice(0, 40).map((e) => (
                  <tr key={e.id}>
                    <td>{e.display_name}</td>
                    <td className="mono" style={{ color: "var(--text-dim)" }}>
                      {e.handles.map(([ns, v]) => `${ns}=${v}`).join("  ·  ")}
                      {e.handles.length === 1 && (
                        // One handle means another channel will not resolve to this person.
                        <span style={{ color: "var(--defer)" }} title="Only one handle">
                          {"  "}!
                        </span>
                      )}
                    </td>
                    <td className="mono" style={{ color: "var(--text-faint)" }}>
                      {Object.entries(e.state)
                        .map(([k, v]) => `${k}=${v}`)
                        .join(", ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
