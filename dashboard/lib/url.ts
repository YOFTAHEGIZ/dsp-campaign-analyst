// Builds the "?advertiser=&from=&to=" part of a link from the current filters.
// Used by the pages (server) and the filter bar (browser), so it lives in a plain module.
// Values equal to the default (all advertisers, first day, last day) are left out.
export function filterQuery(f: { advertiser: number | null; from: string; to: string },
                            days: { date: string }[]) {
  const params = new URLSearchParams();
  if (f.advertiser != null) params.set("advertiser", String(f.advertiser));
  if (days.length && f.from !== days[0].date) params.set("from", f.from);
  if (days.length && f.to !== days[days.length - 1].date) params.set("to", f.to);
  const q = params.toString();
  return q ? `?${q}` : "";
}