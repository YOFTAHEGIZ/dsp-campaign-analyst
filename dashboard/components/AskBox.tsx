"use client";
// The question box and the answers. Every answer shows the SQL that produced its numbers.
import { useState } from "react";
import type { AskResult } from "@/lib/ai";

const EXAMPLES = [
  "Which advertiser had the highest CTR over the whole week?",
  "How much did advertiser 1458 spend on 9 June?",
  "Which hour of the day has the highest CTR across all advertisers?",
  "What share of its bid does each advertiser actually pay?",
  "Which advertiser will have the best CTR next month?",
];

type Item = { question: string; result?: AskResult; error?: string };

export default function AskBox() {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [items, setItems] = useState<Item[]>([]);

  async function submit(q: string) {
    const text = q.trim();
    if (!text || busy) return;
    setBusy(true);
    setQuestion("");
    setItems((list) => [{ question: text }, ...list]);
    let item: Item;
    try {
      const res = await fetch("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" },
                                            body: JSON.stringify({ question: text }) });
      const data = await res.json();
      item = res.ok ? { question: text, result: data } : { question: text, error: data.error ?? `Error ${res.status}` };
    } catch {
      item = { question: text, error: "Could not reach the server. Please try again." };
    }
    setItems((list) => [item, ...list.slice(1)]);
    setBusy(false);
  }

  return (
    <div className="ask">
      <form onSubmit={(e) => { e.preventDefault(); submit(question); }}>
        <textarea value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={500} rows={2}
                  placeholder="Ask a question about the campaigns, e.g. Which day had the most clicks for 3386?"
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(question); } }} />
        <button type="submit" disabled={busy || !question.trim()}>{busy ? "Working…" : "Ask"}</button>
      </form>
      <div className="examples">
        {EXAMPLES.map((q) => <button key={q} type="button" onClick={() => submit(q)} disabled={busy}>{q}</button>)}
      </div>
      {items.map((it, i) => <Answer key={items.length - i} item={it} />)}
    </div>
  );
}

function Answer({ item }: { item: Item }) {
  const r = item.result;
  return (
    <article className={r && r.status !== "pass" ? "event withheld" : "event"}>
      <div className="event-head"><b>{item.question}</b></div>
      {!r && !item.error && <p className="note">Querying the data and checking the answer…</p>}
      {item.error && <p className="warn">{item.error}</p>}
      {r && (r.status === "pass"
        ? <h3>{r.answer}</h3>
        : <p className="note"><span className="badge held">answer withheld</span> {r.note}</p>)}
      {r && r.queries.length > 0 && (
        <details open={r.status !== "pass"}>
          <summary>Show the SQL behind this ({r.queries.length} {r.queries.length === 1 ? "query" : "queries"})</summary>
          {r.queries.map((q, i) => (
            <div key={i}>
              <pre>{q.sql}</pre>
              <table>
                <thead><tr>{q.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
                <tbody>{q.rows.map((row, j) => <tr key={j}>{row.map((v, k) => <td key={k}>{String(v ?? "–")}</td>)}</tr>)}</tbody>
              </table>
            </div>
          ))}
        </details>
      )}
      {r && r.status === "pass" && (
        <p className="credit">
          Answered by {r.provider} from the query results only · checked by Cohere: {r.verdict?.reason}
        </p>
      )}
    </article>
  );
}