"use client";
// The filter bar: advertiser and date range. Each change updates the URL
// (?advertiser=&from=&to=), so a filtered view can be bookmarked or shared.
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { filterQuery } from "@/lib/url";

type Props = {
  advertisers: { advertiser_id: number; advertiser_name: string }[];
  days: { date: string; label: string }[];
  advertiser: number | null;
  from: string;
  to: string;
};

export default function Filters({ advertisers, days, advertiser, from, to }: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const go = (change: Partial<{ advertiser: number | null; from: string; to: string }>) => {
    const next = { advertiser, from, to, ...change };
    if (next.from > next.to) {
      // keep the range valid: moving "from" past "to" moves "to" too, and the other way
      if (change.from) next.to = next.from; else next.from = next.to;
    }
    router.push(pathname + filterQuery(next, days));
  };
  const filtered = advertiser != null || from !== days[0]?.date || to !== days[days.length - 1]?.date;

  return (
    <div className="filters">
      <label className="picker">
        Advertiser
        <select value={advertiser ?? "all"}
                onChange={(e) => go({ advertiser: e.target.value === "all" ? null : Number(e.target.value) })}>
          <option value="all">All advertisers</option>
          {advertisers.map((a) => (
            <option key={a.advertiser_id} value={a.advertiser_id}>{a.advertiser_name}</option>
          ))}
        </select>
      </label>
      <label className="picker">
        From
        <select value={from} onChange={(e) => go({ from: e.target.value })}>
          {days.map((d) => <option key={d.date} value={d.date}>{d.label}</option>)}
        </select>
      </label>
      <label className="picker">
        To
        <select value={to} onChange={(e) => go({ to: e.target.value })}>
          {days.map((d) => <option key={d.date} value={d.date}>{d.label}</option>)}
        </select>
      </label>
      {filtered && <Link className="reset" href={pathname}>Reset</Link>}
    </div>
  );
}