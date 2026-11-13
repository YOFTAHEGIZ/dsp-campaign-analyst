// Small server-rendered SVG charts: no chart library, so they load instantly.
// Every mark has a <title>, which the browser shows as a tooltip on hover.
import React from "react";

const W = 640;
const PAD = { l: 52, r: 12, t: 12, b: 28 };
export const COLORS = { blue: "#2a78d6", orange: "#eb6834", grey: "#8a8984", ink2: "#52514e", grid: "#e6e5e0" };

function niceScale(v: number): { max: number; ticks: number[] } {
  if (!(v > 0)) return { max: 1, ticks: [0, 0.25, 0.5, 0.75, 1] };
  const raw = v / 5;
  const p = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * p).find((m) => m >= raw)!;
  const max = Math.ceil(v / step - 1e-9) * step;
  const ticks = Array.from({ length: Math.round(max / step) + 1 }, (_, i) => i * step);
  return { max, ticks };
}

function YAxis({ scale, h, w, format }: { scale: { max: number; ticks: number[] }; h: number; w: number; format: (v: number) => string }) {
  const y = (v: number) => PAD.t + (h - PAD.t - PAD.b) * (1 - v / scale.max);
  return (
    <g>
      {scale.ticks.map((t) => (
        <g key={t}>
          <line x1={PAD.l} x2={w - PAD.r} y1={y(t)} y2={y(t)} stroke={COLORS.grid} />
          <text x={PAD.l - 6} y={y(t) + 4} textAnchor="end" fontSize="11" fill={COLORS.ink2}>{format(t)}</text>
        </g>
      ))}
    </g>
  );
}

/** Vertical bars, one per label (e.g. impressions per day). */
export function Bars({ labels, values, format, color = COLORS.blue, height = 190, titles }: {
  labels: string[]; values: number[]; format: (v: number) => string; color?: string; height?: number; titles?: string[];
}) {
  const scale = niceScale(Math.max(...values, 0));
  const iw = (W - PAD.l - PAD.r) / Math.max(labels.length, 1);
  const y = (v: number) => PAD.t + (height - PAD.t - PAD.b) * (1 - v / scale.max);
  return (
    <svg viewBox={`0 0 ${W} ${height}`} className="chart" role="img">
      <YAxis scale={scale} h={height} w={W} format={format} />
      {values.map((v, i) => (
        <g key={i}>
          <rect x={PAD.l + i * iw + iw * 0.18} y={y(v)} width={iw * 0.64} height={Math.max(0, height - PAD.b - y(v))}
                rx={3} fill={color}>
            <title>{titles?.[i] ?? `${labels[i]}: ${format(v)}`}</title>
          </rect>
          <text x={PAD.l + i * iw + iw / 2} y={height - 9} textAnchor="middle" fontSize="11" fill={COLORS.ink2}>{labels[i]}</text>
        </g>
      ))}
    </svg>
  );
}

/** A line with an optional 95% band and an optional reference line (e.g. CTR per day). */
export function Line({ labels, values, lo, hi, reference, referenceLabel, format, height = 190, showEvery = 1, width = W }: {
  labels: string[]; values: (number | null)[]; lo?: number[]; hi?: number[]; reference?: number; referenceLabel?: string;
  format: (v: number) => string; height?: number; showEvery?: number; width?: number;
}) {
  const all = [...values.filter((v): v is number => v != null), ...(hi ?? []).filter(Number.isFinite), reference ?? 0];
  const scale = niceScale(Math.max(...all, 0) * 1.05);
  const max = scale.max;
  const inner = 24;                                     // keeps the first and last label inside the chart
  const iw = (width - PAD.l - PAD.r - 2 * inner) / Math.max(labels.length - 1, 1);
  const x = (i: number) => PAD.l + inner + i * iw;
  const y = (v: number) => PAD.t + (height - PAD.t - PAD.b) * (1 - v / max);
  const pts = values.map((v, i) => (v == null ? null : `${x(i)},${y(v)}`)).filter(Boolean).join(" ");
  const band = lo && hi ? [...hi.map((v, i) => `${x(i)},${y(v)}`), ...lo.map((v, i) => `${x(i)},${y(v)}`).reverse()].join(" ") : null;
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="chart" role="img">
      <YAxis scale={scale} h={height} w={width} format={format} />
      {band && <polygon points={band} fill={COLORS.blue} opacity={0.14} />}
      {reference != null && (
        <g>
          <line x1={PAD.l} x2={width - PAD.r} y1={y(reference)} y2={y(reference)} stroke={COLORS.orange} strokeDasharray="5 4" strokeWidth={1.5} />
          <text x={PAD.l + 4} y={PAD.t + 10} fontSize="11" fill={COLORS.orange}>{`– – ${referenceLabel}: ${format(reference)}`}</text>
        </g>
      )}
      <polyline points={pts} fill="none" stroke={COLORS.blue} strokeWidth={2} />
      {values.map((v, i) => v == null ? null : (
        <circle key={i} cx={x(i)} cy={y(v)} r={labels.length > 30 ? 2 : 4} fill={COLORS.blue}>
          <title>{`${labels[i]}: ${format(v)}${lo && hi ? ` (95% CI ${format(lo[i])}–${format(hi[i])})` : ""}`}</title>
        </circle>
      ))}
      {labels.map((l, i) => i % showEvery === 0 && (
        <text key={i} x={x(i)} y={height - 9} textAnchor="middle" fontSize="11" fill={COLORS.ink2}>{l}</text>
      ))}
    </svg>
  );
}

/** Pacing: cumulative share of each day's spend by hour (thin = each day, thick = average, dashed = even). */
export function Pacing({ days, height = 230 }: { days: { label: string; cum: number[] }[]; height?: number }) {
  const iw = (W - PAD.l - PAD.r - 24) / 24;
  const x = (h: number) => PAD.l + 8 + h * iw;
  const y = (v: number) => PAD.t + (height - PAD.t - PAD.b) * (1 - v);
  const avg = Array.from({ length: 24 }, (_, h) => days.reduce((s, d) => s + d.cum[h], 0) / Math.max(days.length, 1));
  const line = (c: number[]) => [`${x(0)},${y(0)}`, ...c.map((v, h) => `${x(h + 1)},${y(v)}`)].join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${height}`} className="chart" role="img">
      <YAxis scale={{ max: 1, ticks: [0, 0.25, 0.5, 0.75, 1] }} h={height} w={W} format={(v) => `${Math.round(v * 100)}%`} />
      <line x1={x(0)} y1={y(0)} x2={x(24)} y2={y(1)} stroke={COLORS.grey} strokeDasharray="5 4" />
      {days.map((d) => (
        <polyline key={d.label} points={line(d.cum)} fill="none" stroke={COLORS.blue} strokeWidth={1} opacity={0.35}>
          <title>{d.label}</title>
        </polyline>
      ))}
      <polyline points={line(avg)} fill="none" stroke={COLORS.blue} strokeWidth={2.5} />
      {avg.map((v, h) => (
        <circle key={h} cx={x(h + 1)} cy={y(v)} r={6} fill="transparent">
          <title>{`by ${String(h + 1).padStart(2, "0")}:00 — ${Math.round(v * 100)}% of the day's spend (even pacing: ${Math.round(((h + 1) / 24) * 100)}%)`}</title>
        </circle>
      ))}
      {[0, 6, 12, 18, 24].map((h) => (
        <text key={h} x={x(h)} y={height - 9} textAnchor="middle" fontSize="11" fill={COLORS.ink2}>{`${String(h).padStart(2, "0")}:00`}</text>
      ))}
    </svg>
  );
}

/** Horizontal bars with value labels (categories). */
export function HBars({ labels, values, format, color = COLORS.blue, titles }: {
  labels: string[]; values: number[]; format: (v: number) => string; color?: string; titles?: string[];
}) {
  const rowH = 30;
  const height = labels.length * rowH + 10;
  const left = 110;
  const max = Math.max(...values, 0) || 1;
  const bw = (v: number) => ((W - left - 80) * v) / max;
  return (
    <svg viewBox={`0 0 ${W} ${height}`} className="chart" role="img">
      {labels.map((l, i) => (
        <g key={l}>
          <text x={left - 8} y={i * rowH + 22} textAnchor="end" fontSize="12" fill={COLORS.ink2}>{l}</text>
          <rect x={left} y={i * rowH + 8} width={Math.max(bw(values[i]), 1)} height={18} rx={3} fill={color}>
            <title>{titles?.[i] ?? `${l}: ${format(values[i])}`}</title>
          </rect>
          <text x={left + bw(values[i]) + 6} y={i * rowH + 22} fontSize="12" fill={COLORS.ink2}>{format(values[i])}</text>
        </g>
      ))}
    </svg>
  );
}

/** Two bars per category (e.g. average bid vs average paid). */
export function PairBars({ labels, a, b, aName, bName, format, height = 210 }: {
  labels: string[]; a: number[]; b: number[]; aName: string; bName: string; format: (v: number) => string; height?: number;
}) {
  const scale = niceScale(Math.max(...a, ...b, 0));
  const iw = (W - PAD.l - PAD.r) / Math.max(labels.length, 1);
  const y = (v: number) => PAD.t + (height - PAD.t - PAD.b) * (1 - v / scale.max);
  return (
    <div>
      <div className="legend"><span className="sw" style={{ background: COLORS.grey }} />{aName}<span className="sw" style={{ background: COLORS.blue }} />{bName}</div>
      <svg viewBox={`0 0 ${W} ${height}`} className="chart" role="img">
        <YAxis scale={scale} h={height} w={W} format={format} />
        {labels.map((l, i) => (
          <g key={l}>
            <rect x={PAD.l + i * iw + iw * 0.14} y={y(a[i])} width={iw * 0.34} height={height - PAD.b - y(a[i])} rx={3} fill={COLORS.grey}>
              <title>{`${l} — ${aName}: ${format(a[i])}`}</title>
            </rect>
            <rect x={PAD.l + i * iw + iw * 0.52} y={y(b[i])} width={iw * 0.34} height={height - PAD.b - y(b[i])} rx={3} fill={COLORS.blue}>
              <title>{`${l} — ${bName}: ${format(b[i])}`}</title>
            </rect>
            <text x={PAD.l + i * iw + iw / 2} y={height - 9} textAnchor="middle" fontSize="11" fill={COLORS.ink2}>{l}</text>
          </g>
        ))}
      </svg>
    </div>
  );
}