// Page frame: title, filters, tabs and data freshness.
import Link from "next/link";
import AutoRefresh from "./AutoRefresh";
import Filters from "./Filters";
import { filterQuery } from "@/lib/url";
import type { Advertiser, Day, Filters as FilterValues, Status } from "@/lib/data";

export default function Shell({ tab, advertisers, days, filters, lastLoad, status, children }: {
  tab: "performance" | "auction" | "changes" | "ask"; advertisers: Advertiser[]; days: Day[]; filters: FilterValues;
  lastLoad: string | null; status: Status; children: React.ReactNode;
}) {
  const q = filterQuery(filters, days);      // the tabs keep the current filters
  const name = filters.advertiser == null
    ? "All advertisers"
    : advertisers.find((a) => a.advertiser_id === filters.advertiser)?.advertiser_name;
  const label = (date: string) => days.find((d) => d.date === date)?.label ?? date;

  return (
    <main>
      <header>
        <div>
          <h1>DSP Campaign Analyst</h1>
          <p className="sub">
            iPinYou Season 2 · {name} · {label(filters.from)} to {label(filters.to)}
          </p>
          {status && (
            <p className="status">
              <span className={status.mode === "hourly" ? "dot live" : "dot"} />
              Data up to {upToLabel(status.upTo)}
              {status.mode === "hourly" ? " · hourly replay, updates every tick" : ""}
            </p>
          )}
        </div>
        <Filters advertisers={advertisers} days={days} {...filters} />
      </header>
      <nav>
        <Link href={`/${q}`} className={tab === "performance" ? "on" : ""}>Performance &amp; pacing</Link>
        <Link href={`/auction${q}`} className={tab === "auction" ? "on" : ""}>Auction insights</Link>
        <Link href={`/changes${q}`} className={tab === "changes" ? "on" : ""}>What changed</Link>
        <Link href={`/ask${q}`} className={tab === "ask" ? "on" : ""}>Ask the data</Link>
      </nav>
      {children}
      <AutoRefresh seconds={60} />
      <footer>
        Rates are ratios of sums over the selected advertiser and days. Clicks and conversions count on
        the day the ad was shown. Spend is the paying price ÷ 1,000. Source: Neon
        {lastLoad ? ` · data loaded ${lastLoad} UTC` : ""}.
      </footer>
    </main>
  );
}

/** "2013-06-07 15:00" -> "Fri 07 Jun 2013, 15:00" */
function upToLabel(upTo: string) {
  const [date, time] = upTo.split(" ");
  const day = new Date(date + "T00:00:00Z").toLocaleDateString("en-GB", {
    weekday: "short", day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });
  return `${day}, ${time}`;
}

export function Kpi({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="kpi">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {note && <div className="kpi-note">{note}</div>}
    </div>
  );
}

export function NoDatabase() {
  return (
    <main>
      <h1>DSP Campaign Analyst</h1>
      <p>NEON_DATABASE_URL is not set. Add your Neon connection string to <code>.env.local</code> (local) or to the
        Vercel project&apos;s environment variables, then run the pipeline.</p>
    </main>
  );
}

export function NoData() {
  return <p className="warn">No data for this selection. Run the pipeline (python pipeline/src/pipeline/run.py) to load Neon.</p>;
}