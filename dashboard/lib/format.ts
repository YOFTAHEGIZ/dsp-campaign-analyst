// Number formatting and the Wilson interval, shared by every page.
export const fmtInt = (v: number | null | undefined) =>
  v == null || Number.isNaN(v) ? "–" : Math.round(v).toLocaleString("en-US");

export const fmtPct = (v: number | null | undefined, digits = 2) =>
  v == null || !Number.isFinite(v) ? "–" : `${(100 * v).toFixed(digits)}%`;

export const fmtNum = (v: number | null | undefined, digits = 1) =>
  v == null || !Number.isFinite(v) ? "–" : v.toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: digits });

export const fmtCompact = (v: number) =>
  Math.abs(v) >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : Math.abs(v) >= 1e3 ? `${(v / 1e3).toFixed(0)}k` : `${Math.round(v)}`;

export const fmtDate = (d: string) =>
  new Date(d + "T00:00:00Z").toLocaleDateString("en-GB", { weekday: "short", day: "2-digit", month: "short", timeZone: "UTC" });

/** 95% Wilson score interval for k successes out of n. */
export function wilson(k: number, n: number, z = 1.959964): [number, number] {
  if (!n) return [NaN, NaN];
  const p = k / n;
  const d = 1 + (z * z) / n;
  const c = (p + (z * z) / (2 * n)) / d;
  const h = (z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))) / d;
  return [Math.max(0, c - h), Math.min(1, c + h)];
}

/** a / b, or null when b is 0 (a rate with nothing under it is undefined, not zero). */
export const ratio = (a: number, b: number) => (b ? a / b : null);