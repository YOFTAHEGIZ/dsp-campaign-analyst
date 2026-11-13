// Tab 2: auction insights for the selected advertiser and dates:
// win rate, what we bid vs what we pay, and the effect of floor prices.
import Shell, { Kpi, NoData, NoDatabase } from "@/components/Shell";
import { HBars, Line, PairBars } from "@/components/charts";
import { hasDatabase } from "@/lib/db";
import { getAdvertisers, getAuction, getDays, getLastLoad, getStatus, parseFilters, type AuctionRow } from "@/lib/data";
import { fmtDate, fmtInt, fmtNum, fmtPct, ratio, wilson } from "@/lib/format";

export const instant = false;

type Search = { advertiser?: string; from?: string; to?: string };

const total = (rows: AuctionRow[]) => rows.reduce((a, r) => ({
  bids: a.bids + r.bids, wins: a.wins + r.wins, sum_bid_price: a.sum_bid_price + r.sum_bid_price,
  sum_bid_price_won: a.sum_bid_price_won + r.sum_bid_price_won, sum_paying_price: a.sum_paying_price + r.sum_paying_price,
  floor_set_price: a.floor_set_price + r.floor_set_price, paid_above_bid: a.paid_above_bid + r.paid_above_bid,
  paid_below_floor: a.paid_below_floor + r.paid_below_floor,
}), { bids: 0, wins: 0, sum_bid_price: 0, sum_bid_price_won: 0, sum_paying_price: 0, floor_set_price: 0,
      paid_above_bid: 0, paid_below_floor: 0 });

export default async function Auction({ searchParams }: { searchParams: Promise<Search> }) {
  if (!hasDatabase) return <NoDatabase />;
  const [sp, advertisers, days, lastLoad, status] = await Promise.all([
    searchParams, getAdvertisers(), getDays(), getLastLoad(), getStatus()]);
  const filters = parseFilters(sp, advertisers, days);
  const [byExchange, byFloor, byDate] = await Promise.all([
    getAuction(filters, "ad_exchange"), getAuction(filters, "floor_band"), getAuction(filters, "date")]);

  const shell = { advertisers, days, filters, lastLoad, status };
  if (!byDate.length) return <Shell tab="auction" {...shell}><NoData /></Shell>;

  const t = total(byDate);
  const winRate = ratio(t.wins, t.bids);
  const paidToBid = ratio(t.sum_paying_price, t.sum_bid_price_won);
  const dailyCi = byDate.map((d) => wilson(d.wins, d.bids));

  return (
    <Shell tab="auction" {...shell}>
      {t.bids === 0 && (
        <p className="warn">No bids for this selection, so win rate is not available. Bid vs paid uses won impressions only.</p>
      )}
      <p className="note">Prices are the log values: per 1,000 impressions, scaled by iPinYou.</p>
      <section className="kpis">
        <Kpi label="Bids" value={fmtInt(t.bids)} />
        <Kpi label="Win rate" value={fmtPct(winRate, 1)} note={`${fmtInt(t.wins)} auctions won`} />
        <Kpi label="Average bid" value={fmtNum(ratio(t.sum_bid_price, t.bids))} note="all bids" />
        <Kpi label="Average paid" value={fmtNum(ratio(t.sum_paying_price, t.wins))} note="won impressions" />
        <Kpi label="Paid ÷ bid" value={fmtPct(paidToBid, 0)}
             note={paidToBid == null ? "" : `we pay ${fmtPct(paidToBid, 0)} of what we bid`} />
        <Kpi label="Floor set the price" value={fmtPct(ratio(t.floor_set_price, t.wins), 1)} note="of won impressions" />
        <Kpi label="Paid above bid" value={fmtPct(ratio(t.paid_above_bid, t.wins), 2)}
             note={`${fmtInt(t.paid_above_bid)} impressions, flagged`} />
        <Kpi label="Paid below floor" value={fmtPct(ratio(t.paid_below_floor, t.wins), 2)}
             note={`${fmtInt(t.paid_below_floor)} impressions, flagged`} />
      </section>

      <section className="grid2">
        <div className="card">
          <h2>Win rate per day, with 95% interval</h2>
          <Line labels={byDate.map((d) => fmtDate(d.key))} values={byDate.map((d) => ratio(d.wins, d.bids))}
                lo={dailyCi.map((c) => c[0])} hi={dailyCi.map((c) => c[1])} reference={winRate ?? undefined}
                referenceLabel="selection" format={(v) => fmtPct(v, 1)} />
        </div>
        <div className="card">
          <h2>Average bid vs average paid, by ad exchange</h2>
          <PairBars labels={byExchange.map((r) => `exchange ${r.key}`)}
                    a={byExchange.map((r) => ratio(r.sum_bid_price_won, r.wins) ?? 0)}
                    b={byExchange.map((r) => ratio(r.sum_paying_price, r.wins) ?? 0)}
                    aName="average bid (won)" bName="average paid" format={(v) => fmtNum(v, 0)} />
        </div>
        <div className="card">
          <h2>Win rate by floor price</h2>
          <HBars labels={byFloor.map((r) => `floor ${r.key}`)} values={byFloor.map((r) => ratio(r.wins, r.bids) ?? 0)}
                 format={(v) => fmtPct(v, 1)}
                 titles={byFloor.map((r) => `floor ${r.key}: ${fmtPct(ratio(r.wins, r.bids), 1)} of ${fmtInt(r.bids)} bids`)} />
        </div>
        <div className="card">
          <h2>How often the floor set the price</h2>
          <HBars labels={byFloor.map((r) => `floor ${r.key}`)} values={byFloor.map((r) => ratio(r.floor_set_price, r.wins) ?? 0)}
                 format={(v) => fmtPct(v, 0)} />
        </div>
      </section>

      <section className="card">
        <h2>By ad exchange</h2>
        <table>
          <thead>
            <tr><th>Exchange</th><th>Bids</th><th>Wins</th><th>Win rate</th><th>Avg bid</th><th>Avg paid</th>
              <th>Paid ÷ bid</th><th>Floor set price</th></tr>
          </thead>
          <tbody>
            {byExchange.map((r) => (
              <tr key={r.key}>
                <td>{r.key}</td><td>{fmtInt(r.bids)}</td><td>{fmtInt(r.wins)}</td>
                <td>{fmtPct(ratio(r.wins, r.bids), 1)}</td><td>{fmtNum(ratio(r.sum_bid_price, r.bids))}</td>
                <td>{fmtNum(ratio(r.sum_paying_price, r.wins))}</td>
                <td>{fmtPct(ratio(r.sum_paying_price, r.sum_bid_price_won), 0)}</td>
                <td>{fmtPct(ratio(r.floor_set_price, r.wins), 1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </Shell>
  );
}