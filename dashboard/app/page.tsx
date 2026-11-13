// Tab 1: performance and pacing for the selected advertiser and dates.
import Link from "next/link";
import Shell, { Kpi, NoData, NoDatabase } from "@/components/Shell";
import { filterQuery } from "@/lib/url";
import { Bars, Line, Pacing } from "@/components/charts";
import { hasDatabase } from "@/lib/db";
import {
  getAdvertisers, getByAdvertiser, getDaily, getDays, getHourly, getLastLoad, getStatus, parseFilters,
} from "@/lib/data";
import { fmtCompact, fmtDate, fmtInt, fmtNum, fmtPct, ratio, wilson } from "@/lib/format";

// The page reads the database on every request (the filters come from the URL)
export const instant = false;

type Search = { advertiser?: string; from?: string; to?: string };

export default async function Performance({ searchParams }: { searchParams: Promise<Search> }) {
  if (!hasDatabase) return <NoDatabase />;
  const [sp, advertisers, days, lastLoad, status] = await Promise.all([
    searchParams, getAdvertisers(), getDays(), getLastLoad(), getStatus()]);
  const filters = parseFilters(sp, advertisers, days);
  const [daily, hourly, compare] = await Promise.all([
    getDaily(filters), getHourly(filters), getByAdvertiser(filters)]);

  const shell = { advertisers, days, filters, lastLoad, status };
  if (!daily.length) return <Shell tab="performance" {...shell}><NoData /></Shell>;

  // Totals for the selection: every rate below is a ratio of these sums
  const t = daily.reduce((a, d) => ({
    impressions: a.impressions + d.impressions, clicks: a.clicks + d.clicks, clicked: a.clicked + d.clicked,
    conversions: a.conversions + d.conversions, converted: a.converted + d.converted,
    post_click: a.post_click + d.post_click, cost: a.cost + d.cost, bids: a.bids + d.bids, wins: a.wins + d.wins,
  }), { impressions: 0, clicks: 0, clicked: 0, conversions: 0, converted: 0, post_click: 0, cost: 0, bids: 0, wins: 0 });

  const ctr = ratio(t.clicked, t.impressions);
  const [ctrLo, ctrHi] = wilson(t.clicked, t.impressions);

  // Last day compared with the average of the earlier days in the selection
  const last = daily[daily.length - 1];
  const earlier = daily.slice(0, -1);
  const avg = (f: (d: (typeof daily)[number]) => number) =>
    earlier.reduce((s, d) => s + f(d), 0) / Math.max(earlier.length, 1);
  const vsEarlier = (cur: number, base: number) =>
    earlier.length && base ? `last day ${cur >= base ? "+" : ""}${(100 * (cur / base - 1)).toFixed(0)}% vs earlier days` : "";

  const labels = daily.map((d) => fmtDate(d.date));
  const dailyCi = daily.map((d) => wilson(d.clicked, d.impressions));

  // Pacing: for each day, the running share of that day's spend by hour
  const spendByDay = new Map<string, number[]>();
  for (const h of hourly) {
    if (!spendByDay.has(h.date)) spendByDay.set(h.date, Array(24).fill(0));
    spendByDay.get(h.date)![h.hour] += h.cost;
  }
  const pacing = [...spendByDay.entries()].map(([date, cost]) => {
    const total = cost.reduce((s, v) => s + v, 0) || 1;
    let running = 0;
    return { label: fmtDate(date), cum: cost.map((v) => (running += v) / total) };
  });
  const spentByNoon = pacing.length ? pacing.reduce((s, d) => s + d.cum[11], 0) / pacing.length : 0;

  // CTR by hour of day, all selected days together
  const byHour = Array.from({ length: 24 }, (_, h) => hourly.filter((r) => r.hour === h)
    .reduce((a, r) => ({ imp: a.imp + r.impressions, clk: a.clk + r.clicked }), { imp: 0, clk: 0 }));
  const hourCi = byHour.map((h) => wilson(h.clk, h.imp));

  const names = new Map(advertisers.map((a) => [a.advertiser_id, a.advertiser_name]));

  return (
    <Shell tab="performance" {...shell}>
      <section className="kpis">
        <Kpi label="Impressions" value={fmtInt(t.impressions)}
             note={vsEarlier(last.impressions, avg((d) => d.impressions))} />
        <Kpi label="Spend" value={fmtInt(t.cost)} note={vsEarlier(last.cost, avg((d) => d.cost))} />
        <Kpi label="CPM" value={fmtNum(ratio(1000 * t.cost, t.impressions))} note="spend per 1,000 impressions" />
        <Kpi label="Clicks" value={fmtInt(t.clicks)} note={`${fmtInt(t.clicked)} clicked impressions`} />
        <Kpi label="CTR" value={fmtPct(ctr, 3)} note={`95% CI ${fmtPct(ctrLo, 3)}–${fmtPct(ctrHi, 3)}`} />
        <Kpi label="CPC" value={fmtNum(ratio(t.cost, t.clicked))} note="spend per clicked impression" />
        <Kpi label="Conversions" value={fmtInt(t.conversions)} note={`${fmtInt(t.post_click)} after a click`} />
        <Kpi label="CVR" value={fmtPct(ratio(t.post_click, t.clicked), 1)} note="post-click conversions ÷ clicks" />
        <Kpi label="CPA" value={fmtNum(ratio(t.cost, t.converted), 0)}
             note={t.converted ? "spend per converted impression" : "no conversions"} />
        <Kpi label="Win rate" value={fmtPct(ratio(t.wins, t.bids), 1)} note={`${fmtInt(t.bids)} bids`} />
      </section>

      <section className="grid2">
        <div className="card">
          <h2>Impressions per day</h2>
          <Bars labels={labels} values={daily.map((d) => d.impressions)} format={fmtCompact}
                titles={daily.map((d) => `${fmtDate(d.date)}: ${fmtInt(d.impressions)} impressions`)} />
        </div>
        <div className="card">
          <h2>Spend per day</h2>
          <Bars labels={labels} values={daily.map((d) => d.cost)} format={fmtCompact}
                titles={daily.map((d) => `${fmtDate(d.date)}: ${fmtInt(d.cost)} spend`)} />
        </div>
        <div className="card">
          <h2>CTR per day, with 95% interval</h2>
          <Line labels={labels} values={daily.map((d) => ratio(d.clicked, d.impressions))}
                lo={dailyCi.map((c) => c[0])} hi={dailyCi.map((c) => c[1])}
                reference={ctr ?? undefined} referenceLabel="selection" format={(v) => fmtPct(v, 3)} />
        </div>
        <div className="card">
          <h2>Pacing: share of the day&apos;s spend by hour</h2>
          <p className="hint">
            Thin lines are single days, the thick line is the average, dashed is even pacing.
            On average {Math.round(spentByNoon * 100)}% of a day&apos;s spend is gone by noon.
          </p>
          <Pacing days={pacing} />
        </div>
        <div className="card wide">
          <h2>CTR by hour of day, with 95% interval</h2>
          <Line labels={Array.from({ length: 24 }, (_, h) => `${String(h).padStart(2, "0")}h`)}
                values={byHour.map((h) => ratio(h.clk, h.imp))}
                lo={hourCi.map((c) => c[0])} hi={hourCi.map((c) => c[1])} reference={ctr ?? undefined}
                referenceLabel="average" format={(v) => fmtPct(v, 3)} showEvery={3} width={1240} height={220} />
        </div>
      </section>

      <section className="card">
        <h2>Advertisers compared</h2>
        <p className="note">Same dates for every advertiser. Click a name to select it.</p>
        <table>
          <thead>
            <tr><th>Advertiser</th><th>Impressions</th><th>Spend</th><th>CPM</th><th>CTR</th><th>CPC</th>
              <th>Conversions</th><th>CPA</th><th>Win rate</th></tr>
          </thead>
          <tbody>
            {compare.map((a) => (
              <tr key={a.advertiser_id} style={a.advertiser_id === filters.advertiser ? { fontWeight: 650 } : undefined}>
                <td className="name">
                  <Link href={`/${filterQuery({ ...filters, advertiser: a.advertiser_id }, days)}`}>
                    {names.get(a.advertiser_id) ?? a.advertiser_id}
                  </Link>
                </td>
                <td>{fmtInt(a.impressions)}</td><td>{fmtInt(a.cost)}</td>
                <td>{fmtNum(ratio(1000 * a.cost, a.impressions))}</td>
                <td>{fmtPct(ratio(a.clicked, a.impressions), 3)}</td>
                <td>{fmtNum(ratio(a.cost, a.clicked))}</td>
                <td>{fmtInt(a.conversions)}</td>
                <td>{fmtNum(ratio(a.cost, a.converted), 0)}</td>
                <td>{fmtPct(ratio(a.wins, a.bids), 1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="card">
        <h2>Daily KPIs</h2>
        <table>
          <thead>
            <tr><th>Day</th><th>Bids</th><th>Impressions</th><th>Win rate</th><th>Clicks</th><th>CTR</th>
              <th>Conversions</th><th>Spend</th><th>CPM</th><th>CPC</th></tr>
          </thead>
          <tbody>
            {daily.map((d) => (
              <tr key={d.date}>
                <td>{fmtDate(d.date)}</td><td>{fmtInt(d.bids)}</td><td>{fmtInt(d.impressions)}</td>
                <td>{fmtPct(ratio(d.wins, d.bids), 1)}</td><td>{fmtInt(d.clicks)}</td>
                <td>{fmtPct(ratio(d.clicked, d.impressions), 3)}</td><td>{fmtInt(d.conversions)}</td>
                <td>{fmtInt(d.cost)}</td><td>{fmtNum(ratio(1000 * d.cost, d.impressions))}</td>
                <td>{fmtNum(ratio(d.cost, d.clicked))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </Shell>
  );
}