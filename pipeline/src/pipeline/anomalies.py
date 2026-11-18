"""
Find unusual hours for the "What changed" tab.

    python pipeline/src/pipeline/anomalies.py          find, store and list the unusual hours

Why hourly, and why "same hour on other days":
    7 days is too short for a daily rolling baseline. So each campaign-hour (e.g. 1458 on 9 June
    at 22:00) is compared with the SAME hour on that campaign's OTHER days (22:00 on the other
    6 days). An evening peak is then not flagged just for being evening; only a truly odd hour is.

Metrics, two kinds of z-score:
    ctr       clicked impressions / impressions   proportion test:  z = (p - p0) / sqrt(p0 (1 - p0) / n)
    win_rate  impressions / bids                  proportion test; OFF unless ANOMALY_WIN_RATE=1 (see below)
    impressions, spend, cpm                       z = (x - mean) / sd of the same hour on other days

    Flagged when BOTH are true:
      |z| >= ANOMALY_Z (default 3)              it is very unlikely to be noise (about 3 in 1,000), and
      change >= ANOMALY_MIN_CHANGE (default 25%) it is big enough to matter (effect size, not only
                                                 significance: with millions of rows a 2% wobble
                                                 can have a large z and still not matter)
    Small hours are skipped (too little data to tell): see the MIN_* settings below.

Input: hourly_pacing in Neon (what the dashboard reads). Output: the anomalies table in Neon,
recomputed completely every run, so running it twice changes nothing.
"""

import math
import os
import statistics
from collections import defaultdict
from pathlib import Path

import psycopg
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")
DATABASE_URL = os.getenv("NEON_DATABASE_URL")
AI_SCHEMA = PROJECT_ROOT / "pipeline" / "sql" / "neon" / "ai_schema.sql"

Z_FLAG = float(os.getenv("ANOMALY_Z", "3"))
MIN_CHANGE = float(os.getenv("ANOMALY_MIN_CHANGE", "0.25"))   # and at least 25% away from the baseline
MIN_BASELINE_DAYS = 3          # need at least 3 other days for a baseline
MIN_EXPECTED_CLICKS = 5        # ctr: impressions x baseline CTR must reach this
MIN_BIDS = 1000                # win_rate: bids in the hour
MIN_IMPRESSIONS = 200          # impressions/spend/cpm: baseline average must reach this
# Hourly win rate is OFF by default: bids and impressions come from different log files, and around
# midnight and in the early hours they don't line up hour by hour (e.g. 3427 at 01:00 swings between
# 1% and 76%). That is a logging artefact, not a business event. Win rate stays on the dashboard per day.
HOURLY_WIN_RATE = os.getenv("ANOMALY_WIN_RATE", "0") == "1"
METRICS = ["ctr", "win_rate", "impressions", "spend", "cpm"] if HOURLY_WIN_RATE else \
          ["ctr", "impressions", "spend", "cpm"]


def proportion_z(k, n, k0, n0):
    """This hour's rate k/n vs the baseline rate k0/n0, in standard errors."""
    if n <= 0 or n0 <= 0:
        return None
    p, p0 = k / n, k0 / n0
    if p0 <= 0 or p0 >= 1:
        return None
    return (p - p0) / math.sqrt(p0 * (1 - p0) / n)


def mean_z(x, others):
    """x vs the mean and spread of the other days."""
    if len(others) < MIN_BASELINE_DAYS:
        return None, None
    m, sd = statistics.mean(others), statistics.stdev(others)
    if sd == 0:
        return None, m
    return (x - m) / sd, m


def find(rows):
    """rows: (advertiser_id, report_date, hour, bids, impressions, clicked, cost).
    Returns a list of anomaly dicts, strongest first."""
    by_slot = defaultdict(dict)                       # (advertiser, hour) -> {date: row}
    for adv, day, hour, bids, imps, clicked, cost in rows:
        by_slot[(adv, hour)][day] = (bids or 0, imps or 0, clicked or 0, float(cost or 0))

    found = []
    for (adv, hour), days in by_slot.items():
        for day, (bids, imps, clicked, cost) in days.items():
            others = [v for d, v in days.items() if d != day]
            if len(others) < MIN_BASELINE_DAYS:
                continue
            o_bids = sum(o[0] for o in others)
            o_imps = sum(o[1] for o in others)
            o_clicked = sum(o[2] for o in others)

            def add(metric, value, baseline, z):
                change = (value - baseline) / baseline if baseline else None
                if z is not None and abs(z) >= Z_FLAG and change is not None and abs(change) >= MIN_CHANGE:
                    found.append({"advertiser_id": adv, "report_date": day, "hour": hour,
                                  "metric": metric, "value": value, "baseline": baseline,
                                  "z": round(z, 2), "change": round(change, 4), "direction": "up" if z > 0 else "down",
                                  "baseline_days": len(others)})

            # ctr: enough expected clicks in this hour?
            if o_imps and imps and imps * o_clicked / o_imps >= MIN_EXPECTED_CLICKS:
                add("ctr", clicked / imps, o_clicked / o_imps,
                    proportion_z(clicked, imps, o_clicked, o_imps))
            # win rate: only where bids exist (bid data may cover only some advertisers)
            if HOURLY_WIN_RATE and bids >= MIN_BIDS and o_bids > 0:
                add("win_rate", imps / bids, o_imps / o_bids, proportion_z(imps, bids, o_imps, o_bids))
            # volumes and price
            if o_imps / len(others) >= MIN_IMPRESSIONS:
                z, m = mean_z(imps, [o[1] for o in others])
                add("impressions", imps, m, z)
                z, m = mean_z(cost, [o[3] for o in others])
                add("spend", cost, m, z)
                cpms = [1000 * o[3] / o[1] for o in others if o[1] >= MIN_IMPRESSIONS]
                if imps >= MIN_IMPRESSIONS:
                    z, m = mean_z(1000 * cost / imps, cpms)
                    add("cpm", 1000 * cost / imps, m, z)

    found.sort(key=lambda a: -abs(a["z"]))
    return found


def detect(quiet=False):
    """Recompute the anomalies table from hourly_pacing. Returns the anomalies found."""
    if not DATABASE_URL:
        raise SystemExit("NEON_DATABASE_URL was not found in .env")
    with psycopg.connect(DATABASE_URL, connect_timeout=30) as con:
        con.execute(AI_SCHEMA.read_text())
        rows = con.execute("""
            SELECT advertiser_id, report_date, hour, bids, impressions, clicked_impressions, total_cost
            FROM hourly_pacing""").fetchall()
        found = find(rows)
        with con.transaction():                       # all or nothing
            con.execute("DELETE FROM anomalies")
            with con.cursor() as cur:
                cur.executemany(
                    """INSERT INTO anomalies (advertiser_id, report_date, hour, metric, value, baseline,
                                              z, change, direction, baseline_days)
                       VALUES (%(advertiser_id)s, %(report_date)s, %(hour)s, %(metric)s, %(value)s,
                               %(baseline)s, %(z)s, %(change)s, %(direction)s, %(baseline_days)s)""", found)
    if not quiet:
        days = len({r[1] for r in rows})
        hours = len({(a["advertiser_id"], a["report_date"], a["hour"]) for a in found})
        print(f"Anomalies: {len(found)} flags in {hours} unusual campaign-hour(s), {days} day(s) of data "
              f"(|z| >= {Z_FLAG:g} and change >= {MIN_CHANGE:.0%}, vs the same hour on other days)")
        counts = defaultdict(int)
        for a in found:
            counts[a["metric"]] += 1
        print("  by metric: " + ", ".join(f"{m} {counts[m]}" for m in METRICS))
        for a in found[:10]:
            fmt = (lambda v: f"{100 * v:.3f}%") if a["metric"] in ("ctr", "win_rate") else (lambda v: f"{v:,.1f}")
            print(f"  {a['advertiser_id']} {a['report_date']} {a['hour']:02d}:00  {a['metric']:<11} "
                  f"{fmt(a['value'])} vs {fmt(a['baseline'])}  {a['change']:+.0%}  z={a['z']:+.1f}")
    return found


if __name__ == "__main__":
    detect()