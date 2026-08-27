"use client";

import { useEffect, useState } from "react";

import Nav from "@/components/Nav";
import {
  declareEntities,
  getEntities,
  parseCustomerCsv,
  type AdminEntity,
} from "@/lib/api";

/**
 * Customer data sync.
 *
 * This is the step that makes cross-vendor policy possible at all. Normalisation unifies
 * different spellings of the SAME detail; it cannot know that a phone number and an email
 * belong to one person. Commons refuses to guess at that — in a system that can block a
 * payment, a wrong merge is far worse than no merge — so the merchant states it, once,
 * from the customer list they already have.
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

  const load = () =>
    getEntities()
      .then((e) => {
        setEntities(e);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));

  useEffect(() => {
    load();
  }, []);

  const preview = csv.trim() ? parseCustomerCsv(csv) : [];

  const submit = async () => {
    setBusy(true);
    setResult(null);
    try {
      const res = await declareEntities(preview);
      setResult(`Imported ${res.seeded} customers.`);
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
          Commons will happily unify <span className="mono">+91 98000 00021</span>,{" "}
          <span className="mono">9800000021</span> and{" "}
          <span className="mono">09800000021</span> on its own — those are one detail
          written three ways. What it will <em>not</em> do is guess that a phone number and
          an email address belong to the same person. You already know that; tell it once.
        </p>

        {error && <div className="err">{error}</div>}

        <h2>Import your customer list</h2>
        <p className="lede">
          Paste CSV with any of these columns:{" "}
          <span className="mono">customer_id, name, phone, email, order_id</span>. Only the
          ones you have — every extra handle is another way an agent can refer to that
          person and still be recognised.
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
            {busy ? "importing…" : `Import ${preview.length || ""} customers`}
          </button>
          <button className="btn btn-quiet" onClick={() => setCsv(SAMPLE)}>
            use the example
          </button>
          {result && <span className="ok">{result}</span>}
        </div>

        {preview.length > 0 && (
          <>
            <h2>Preview</h2>
            <div className="ledger">
              <table>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Handles Commons will link</th>
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
            {preview.length > 8 && (
              <p className="note">…and {preview.length - 8} more.</p>
            )}
          </>
        )}

        <h2>Customers Commons knows ({entities?.length ?? 0})</h2>
        {!entities && !error && <div className="loading">loading…</div>}
        {entities && entities.length === 0 && (
          <div className="empty">
            None yet. Import a list above, or let agents create them — a customer seen for
            the first time gets created automatically, but only with the single handle that
            call carried.
          </div>
        )}
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
                        <span style={{ color: "var(--defer)" }}>
                          {"  "}— only one handle, so contact on another channel will not
                          be recognised as this person
                        </span>
                      )}
                    </td>
                    <td className="mono" style={{ color: "var(--text-faint)" }}>
                      {Object.entries(e.state)
                        .map(([k, v]) => `${k}=${v}`)
                        .join(", ") || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <p className="note">
          Importing again is safe: a handle already pointing at a customer is updated, not
          duplicated. If two vendors disagree about who a handle belongs to, Commons keeps
          what it has and reports the conflict rather than silently repointing it.
        </p>
      </div>
    </>
  );
}
