// All dashboard queries, in one place.
// The Neon tables hold counts and sums only. Every rate (CTR, win rate, CPM...) is computed
// here or on the page as a ratio of sums over the selected advertiser and dates.
import { query } from "./db";

// ---- Filters ---------------------------------------------------------------

/** advertiser = null means all advertisers. Dates are "YYYY-MM-DD", both included. */
export type Filters = { advertiser: number | null; from: string; to: string };

export type Advertiser = { advertiser_id: number; advertiser_name: string; has_bid_logs: boolean };
export type Day = { date: string; label: string };

export async function getAdvertisers(): Promise<Advertiser[]> {
  const rows = await query<Record<string, string>>(
    `SELECT c.advertiser_id, a.advertiser_name, c.has_bid_logs
     FROM dim_campaign c JOIN dim_advertiser a ON a.advertiser_id = c.advertiser_id
     ORDER BY c.advertiser_id`
  );
  return rows.map((r) => ({
    advertiser_id: Number(r.advertiser_id), advertiser_name: r.advertiser_name,
    has_bid_logs: Boolean(r.has_bid_logs),
  }));
}

export async function getDays(): Promise<Day[]> {
  return query<Day>(`SELECT date::text AS date, label FROM dim_date ORDER BY date`);
}

/** Read ?advertiser=&from=&to= from the URL. Anything missing or invalid falls back to "all". */
export function parseFilters(
  sp: { advertiser?: string; from?: string; to?: string },
  advertisers: Advertiser[],
  days: Day[],
): Filters {
  const ids = new Set(advertisers.map((a) => a.advertiser_id));
  const dates = days.map((d) => d.date);
  const first = dates[0] ?? "1970-01-01";
  const last = dates[dates.length - 1] ?? "2999-12-31";
  const advertiser = sp.advertiser && ids.has(Number(sp.advertiser)) ? Number(sp.advertiser) : null;
  let from = sp.from && dates.includes(sp.from) ? sp.from : first;
  let to = sp.to && dates.includes(sp.to) ? sp.to : last;
  if (from > to) [from, to] = [to, from];
  return { advertiser, from, to };
}

/** The WHERE part shared by every query. advertiser_id::text works whether the
 *  column is stored as a number or as text in Neon. */
function where(f: Filters) {
  const params: unknown[] = [f.from, f.to];
  let sql = "report_date BETWEEN $1 AND $2";
  if (f.advertiser != null) {
    params.push(String(f.advertiser));
    sql += " AND advertiser_id::text = $3";
  }
  return { sql, params };
}

const num = (v: unknown) => Number(v ?? 0);

// ---- Performance ---------------------------------------------------------------

export type DailyRow = {
  date: string; impressions: number; clicks: number; clicked: number; conversions: number;
  converted: number; post_click: number; cost: number; bids: number; wins: number;
};

export async function getDaily(f: Filters): Promise<DailyRow[]> {
  const w = where(f);
  const [campaign, auction] = await Promise.all([
    query<Record<string, string>>(
      `SELECT report_date::text AS date, SUM(impressions) AS impressions, SUM(clicks) AS clicks,
              SUM(clicked_impressions) AS clicked, SUM(conversions) AS conversions,
              SUM(converted_impressions) AS converted, SUM(post_click_conversions) AS post_click,
              SUM(total_cost) AS cost
       FROM daily_campaign WHERE ${w.sql} GROUP BY 1 ORDER BY 1`, w.params),
    query<Record<string, string>>(
      `SELECT report_date::text AS date, SUM(bids) AS bids, SUM(wins) AS wins
       FROM daily_auction WHERE ${w.sql} GROUP BY 1`, w.params),
  ]);
  const byDate = new Map(auction.map((r) => [r.date, r]));
  return campaign.map((r) => ({
    date: r.date, impressions: num(r.impressions), clicks: num(r.clicks), clicked: num(r.clicked),
    conversions: num(r.conversions), converted: num(r.converted), post_click: num(r.post_click),
    cost: num(r.cost), bids: num(byDate.get(r.date)?.bids), wins: num(byDate.get(r.date)?.wins),
  }));
}

export type HourRow = { date: string; hour: number; impressions: number; clicked: number; cost: number };

export async function getHourly(f: Filters): Promise<HourRow[]> {
  const w = where(f);
  const rows = await query<Record<string, string>>(
    `SELECT report_date::text AS date, hour, SUM(impressions) AS impressions,
            SUM(clicked_impressions) AS clicked, SUM(total_cost) AS cost
     FROM hourly_pacing WHERE ${w.sql} GROUP BY 1, 2 ORDER BY 1, 2`, w.params);
  return rows.map((r) => ({
    date: r.date, hour: num(r.hour), impressions: num(r.impressions), clicked: num(r.clicked), cost: num(r.cost),
  }));
}

export type AdvertiserRow = {
  advertiser_id: number; impressions: number; clicked: number; conversions: number;
  converted: number; cost: number; bids: number; wins: number;
};

/** One row per advertiser for the selected dates (the comparison table). */
export async function getByAdvertiser(f: Filters): Promise<AdvertiserRow[]> {
  const w = where({ ...f, advertiser: null });
  const [campaign, auction] = await Promise.all([
    query<Record<string, string>>(
      `SELECT advertiser_id::text AS id, SUM(impressions) AS impressions, SUM(clicked_impressions) AS clicked,
              SUM(conversions) AS conversions, SUM(converted_impressions) AS converted, SUM(total_cost) AS cost
       FROM daily_campaign WHERE ${w.sql} GROUP BY 1 ORDER BY 1`, w.params),
    query<Record<string, string>>(
      `SELECT advertiser_id::text AS id, SUM(bids) AS bids, SUM(wins) AS wins
       FROM daily_auction WHERE ${w.sql} GROUP BY 1`, w.params),
  ]);
  const byId = new Map(auction.map((r) => [r.id, r]));
  return campaign.map((r) => ({
    advertiser_id: Number(r.id), impressions: num(r.impressions), clicked: num(r.clicked),
    conversions: num(r.conversions), converted: num(r.converted), cost: num(r.cost),
    bids: num(byId.get(r.id)?.bids), wins: num(byId.get(r.id)?.wins),
  }));
}

// ---- Auction ---------------------------------------------------------------

export type AuctionRow = {
  key: string; bids: number; wins: number; sum_bid_price: number; sum_bid_price_won: number;
  sum_paying_price: number; floor_set_price: number; paid_above_bid: number; paid_below_floor: number;
};

const FLOOR_ORDER = `CASE floor_band WHEN '0' THEN 0 WHEN '1-10' THEN 1 WHEN '11-50' THEN 2
  WHEN '51-100' THEN 3 WHEN '101-200' THEN 4 WHEN '200+' THEN 5 ELSE 6 END`;

export async function getAuction(f: Filters, by: "ad_exchange" | "floor_band" | "date"): Promise<AuctionRow[]> {
  const w = where(f);
  const key = by === "date" ? "report_date::text"
    : by === "ad_exchange" ? "COALESCE(ad_exchange::text, 'unknown')" : "floor_band";
  const order = by === "floor_band" ? `MIN(${FLOOR_ORDER})` : "1";
  const rows = await query<Record<string, string>>(
    `SELECT ${key} AS key, SUM(bids) AS bids, SUM(wins) AS wins, SUM(sum_bid_price) AS sum_bid_price,
            SUM(sum_bid_price_won) AS sum_bid_price_won, SUM(sum_paying_price) AS sum_paying_price,
            SUM(floor_set_price) AS floor_set_price, SUM(paid_above_bid) AS paid_above_bid,
            SUM(paid_below_floor) AS paid_below_floor
     FROM daily_auction WHERE ${w.sql} GROUP BY 1 ORDER BY ${order}`, w.params);
  return rows.map((r) => ({
    key: r.key, bids: num(r.bids), wins: num(r.wins), sum_bid_price: num(r.sum_bid_price),
    sum_bid_price_won: num(r.sum_bid_price_won), sum_paying_price: num(r.sum_paying_price),
    floor_set_price: num(r.floor_set_price), paid_above_bid: num(r.paid_above_bid),
    paid_below_floor: num(r.paid_below_floor),
  }));
}

// ---- Freshness ---------------------------------------------------------------

export type Status = { upTo: string; mode: string } | null;

/** How far the data goes (the pipeline's watermark), e.g. upTo "2013-06-07 15:00". */
export async function getStatus(): Promise<Status> {
  try {
    const r = await query<{ up_to: string; mode: string }>(
      `SELECT to_char(processed_up_to, 'YYYY-MM-DD HH24:MI') AS up_to, mode FROM pipeline_status WHERE id = 1`);
    return r[0]?.up_to ? { upTo: r[0].up_to, mode: r[0].mode } : null;
  } catch {
    return null; // pipeline_status does not exist yet
  }
}

export async function getLastLoad(): Promise<string | null> {
  try {
    const r = await query<{ t: string }>(
      `SELECT to_char(MAX(loaded_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI') AS t FROM load_log`);
    return r[0]?.t ?? null;
  } catch {
    return null; // load_log does not exist yet
  }
}

// ---- What changed (week 3) ---------------------------------------------------
// Unusual hours found by the pipeline (anomalies) and their judged explanations. The AI ran in the
// pipeline, not here: this page only reads what was stored, so it is fast and costs nothing.

export type Flag = { hour: number; metric: string; value: number; baseline: number; change: number; z: number };
export type ChangeEvent = {
  advertiser_id: number; report_date: string; hour: number; end_hour: number;
  status: "pass" | "withheld"; headline: string | null; drivers: string[] | null;
  confidence: "high" | "medium" | "low" | null; note: string | null; sql: string[] | null;
  provider: string | null; flags: Flag[];
};
export type Changes = { events: ChangeEvent[]; waiting: number; ready: boolean };

export async function getChanges(f: Filters): Promise<Changes> {
  const w = where(f);
  try {
    const events = await query<ChangeEvent>(
      `SELECT e.advertiser_id::int AS advertiser_id, e.report_date::text AS report_date, e.hour,
              COALESCE(e.end_hour, e.hour) AS end_hour, e.status, e.headline, e.drivers, e.confidence,
              e.note, e.sql, e.provider,
              COALESCE((SELECT json_agg(json_build_object('hour', a.hour, 'metric', a.metric, 'value', a.value,
                                         'baseline', a.baseline, 'change', a.change, 'z', a.z)
                                        ORDER BY a.hour, a.metric)
                        FROM anomalies a
                        WHERE a.advertiser_id = e.advertiser_id AND a.report_date = e.report_date
                          AND a.hour BETWEEN e.hour AND COALESCE(e.end_hour, e.hour)), '[]') AS flags
       FROM explanations e
       WHERE ${w.sql.replace("report_date", "e.report_date").replace("advertiser_id", "e.advertiser_id")}`,
      w.params);
    const [{ n }] = await query<{ n: string }>(
      `SELECT count(*) AS n FROM anomalies a
       WHERE ${w.sql.replace("report_date", "a.report_date").replace("advertiser_id", "a.advertiser_id")}
         AND NOT EXISTS (SELECT 1 FROM explanations e
                         WHERE e.advertiser_id = a.advertiser_id AND e.report_date = a.report_date
                           AND a.hour BETWEEN e.hour AND COALESCE(e.end_hour, e.hour))`, w.params);
    const strength = (e: ChangeEvent) => Math.max(0, ...e.flags.map((x) => Math.abs(x.z)));
    events.sort((a, b) => strength(b) - strength(a));
    return { events, waiting: Number(n), ready: true };
  } catch {
    return { events: [], waiting: 0, ready: false };   // tables not created yet: run the pipeline
  }
}