// Tab 3: what changed. Unusual hours for the selected advertiser and dates, each with an
// explanation written by Gemini from query results and checked by Cohere before it was stored.
// Everything here was made by the pipeline (explain.py); this page only reads it.
import Shell, { Kpi, NoDatabase } from "@/components/Shell";
import { hasDatabase } from "@/lib/db";
import { getAdvertisers, getChanges, getDays, getLastLoad, getStatus, parseFilters,
         type ChangeEvent, type Flag } from "@/lib/data";
import { fmtDate, fmtInt, fmtNum, fmtPct } from "@/lib/format";

export const instant = false;

type Search = { advertiser?: string; from?: string; to?: string };

const METRIC: Record<string, string> = { ctr: "CTR", impressions: "Impressions", spend: "Spend", cpm: "CPM",
                                         win_rate: "Win rate" };

function fmtValue(metric: string, v: number) {
  if (metric === "ctr" || metric === "win_rate") return fmtPct(v, 3);
  if (metric === "impressions") return fmtInt(v);
  return fmtNum(v, 1);
}

const hh = (h: number) => `${String(h).padStart(2, "0")}:00`;
const hours = (e: ChangeEvent) => e.hour === e.end_hour ? hh(e.hour) : `${hh(e.hour)}–${String(e.end_hour).padStart(2, "0")}:59`;

function Flags({ flags }: { flags: Flag[] }) {
  return (
    <table>
      <thead><tr><th>Hour</th><th>Metric</th><th>This hour</th><th>Usual at this hour</th><th>Change</th><th>z</th></tr></thead>
      <tbody>
        {flags.map((f, i) => (
          <tr key={i}>
            <td>{hh(f.hour)}</td>
            <td>{METRIC[f.metric] ?? f.metric}</td>
            <td>{fmtValue(f.metric, f.value)}</td>
            <td>{fmtValue(f.metric, f.baseline)}</td>
            <td className={f.change > 0 ? "up" : "down"}>{f.change > 0 ? "+" : ""}{Math.round(100 * f.change)}%</td>
            <td>{f.z > 0 ? "+" : ""}{fmtNum(f.z, 1)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Event({ e }: { e: ChangeEvent }) {
  const held = e.status !== "pass";
  return (
    <article className={held ? "event withheld" : "event"}>
      <div className="event-head">
        <b>Advertiser {e.advertiser_id}</b> · {fmtDate(e.report_date)} · {hours(e)}
        {held
          ? <span className="badge held">explanation withheld</span>
          : e.confidence && <span className={`badge ${e.confidence}`}>{e.confidence} confidence</span>}
      </div>
      {held ? (
        <p className="note">The AI explanation did not pass the fact check, so it is not shown. {e.note}</p>
      ) : (
        <>
          <h3>{e.headline}</h3>
          {e.drivers && <ul>{e.drivers.map((d, i) => <li key={i}>{d}</li>)}</ul>}
        </>
      )}
      <Flags flags={e.flags} />
      {e.sql && e.sql.length > 0 && (
        <details>
          <summary>Show the SQL behind this ({e.sql.length} queries)</summary>
          {e.sql.map((s, i) => <pre key={i}>{s}</pre>)}
        </details>
      )}
      {!held && <p className="credit">Written by {e.provider} from the query results above · checked number by number by Cohere</p>}
    </article>
  );
}

export default async function Changes({ searchParams }: { searchParams: Promise<Search> }) {
  if (!hasDatabase) return <NoDatabase />;
  const [sp, advertisers, days, lastLoad, status] = await Promise.all([
    searchParams, getAdvertisers(), getDays(), getLastLoad(), getStatus()]);
  const filters = parseFilters(sp, advertisers, days);
  const { events, waiting, ready } = await getChanges(filters);
  const shell = { advertisers, days, filters, lastLoad, status };
  const passed = events.filter((e) => e.status === "pass").length;

  return (
    <Shell tab="changes" {...shell}>
      <p className="note">
        Each hour is compared with the same hour on that advertiser&apos;s other days. It is flagged when it is
        far from usual (|z| ≥ 3) and the change is at least 25%. Neighbouring flagged hours are one event.
        Explanations are written by AI from database query results only, and shown only if a second AI
        confirms every number and claim.
      </p>
      {!ready ? (
        <p className="warn">No anomalies yet. Run <code>python pipeline/src/pipeline/anomalies.py</code> and
          then <code>python pipeline/src/pipeline/explain.py</code>.</p>
      ) : (
        <>
          <section className="kpis">
            <Kpi label="Events" value={fmtInt(events.length)} note="unusual moments explained or checked" />
            <Kpi label="Explained" value={fmtInt(passed)} note="passed the fact check" />
            <Kpi label="Withheld" value={fmtInt(events.length - passed)} note="failed the fact check twice" />
            <Kpi label="Waiting" value={fmtInt(waiting)} note="flags not explained yet" />
          </section>
          {events.length === 0
            ? <p className="warn">Nothing unusual explained for this advertiser and these dates.</p>
            : <div className="events">{events.map((e) => <Event key={`${e.advertiser_id}-${e.report_date}-${e.hour}`} e={e} />)}</div>}
        </>
      )}
    </Shell>
  );
}