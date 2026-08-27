"use client";

import { useRef, useState } from "react";

import Nav from "@/components/Nav";
import {
  declareEntities,
  readCustomerCsv,
  syncCustomers,
  type CsvImport,
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

const EMPTY: CsvImport = { entities: [], used: [], ignored: [] };

export default function DataPage() {
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sync, setSync] = useState<SyncResult | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [csv, setCsv] = useState<CsvImport>(EMPTY);
  const [fileName, setFileName] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const runSync = async (dryRun: boolean) => {
    setSyncing(true);
    setError(null);
    try {
      setSync(await syncCustomers({ source: "razorpay", limit: 100, dry_run: dryRun }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSyncing(false);
    }
  };

  const takeFile = async (file: File | undefined) => {
    if (!file) return;
    setError(null);
    setResult(null);
    try {
      const parsed = readCustomerCsv(await file.text());
      setCsv(parsed);
      setFileName(file.name);
      if (parsed.entities.length === 0) {
        setError(`No customers found in ${file.name}. Expecting a header row.`);
      }
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const clear = () => {
    setCsv(EMPTY);
    setFileName(null);
    setResult(null);
    if (fileInput.current) fileInput.current.value = "";
  };

  const submit = async () => {
    setBusy(true);
    setResult(null);
    try {
      const res = await declareEntities(csv.entities);
      setResult(`Imported ${res.seeded}`);
      setCsv(EMPTY);
      setFileName(null);
      if (fileInput.current) fileInput.current.value = "";
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

        <h2>Import a CSV</h2>

        <div
          className="dropzone"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            takeFile(e.dataTransfer.files[0]);
          }}
          onClick={() => fileInput.current?.click()}
        >
          <input
            ref={fileInput}
            type="file"
            accept=".csv,text/csv"
            hidden
            onChange={(e) => takeFile(e.target.files?.[0])}
          />
          {fileName ? (
            <>
              <strong>{fileName}</strong>
              <span className="field-hint">
                {csv.entities.length} customers · {csv.used.join(", ")}
              </span>
            </>
          ) : (
            <>
              <strong>Choose a .csv file or drop one here</strong>
              <span className="field-hint">
                customer_id, name, phone, email, order_id
              </span>
            </>
          )}
        </div>

        {csv.ignored.length > 0 && (
          <div className="warn">Columns ignored: {csv.ignored.join(", ")}</div>
        )}

        {csv.entities.length > 0 && (
          <>
            <div className="review-actions">
              <button className="btn" disabled={busy} onClick={submit}>
                {busy ? "importing" : `Import ${csv.entities.length}`}
              </button>
              <button className="btn btn-quiet" onClick={clear}>
                clear
              </button>
            </div>

            <div className="ledger">
              <table>
                <thead>
                  <tr>
                    <th style={{ width: 220 }}>Name</th>
                    <th>Handles Commons will link</th>
                  </tr>
                </thead>
                <tbody>
                  {csv.entities.slice(0, 10).map((p, i) => (
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
            {csv.entities.length > 10 && (
              <p className="note">and {csv.entities.length - 10} more</p>
            )}
          </>
        )}

        {result && <div className="ok-banner">{result}</div>}
      </div>
    </>
  );
}
