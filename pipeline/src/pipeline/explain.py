"""
Explain the unusual hours for the "What changed" tab.

    python pipeline/src/pipeline/explain.py              explain new or changed events (at most 20)
    python pipeline/src/pipeline/explain.py --max 5      at most 5 this run
    python pipeline/src/pipeline/explain.py --dry-run    list the events and their data, no AI calls
    python pipeline/src/pipeline/explain.py --redo --max 3   explain the strongest 3 again

How it works:
    1. Read the flags from the anomalies table (anomalies.py fills it).
    2. Group them into EVENTS: same advertiser, same day, neighbouring hours. "3476 stopped at 11:00"
       is one event, not 26 flags.
    3. For each event, run 4 fixed queries as ai_reader (read-only): the flags, those hours vs the
       usual level, the whole day vs usual, and the ad exchanges that changed most that day.
    4. llm.grounded(): Gemini writes {headline, drivers, confidence} from those results only;
       Cohere checks every number and claim; one retry; otherwise withheld.
    5. Store the result in the explanations table, with the facts and the SQL behind it.

Only events that are new or whose numbers changed are explained (the fingerprint), strongest first,
at most --max per run: this keeps us inside the free tiers (Cohere trial: about 1,000 calls a month).
"""

import argparse
import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path

import psycopg
from dotenv import load_dotenv

import llm

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")
DATABASE_URL = os.getenv("NEON_DATABASE_URL")
MAX_EXPLAIN = int(os.getenv("MAX_EXPLAIN", "20"))

SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "drivers": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 3},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
    "required": ["headline", "drivers", "confidence"],
}

TASK = """Explain this unusual moment for advertiser {adv} on {day_label}, {hours} (China time).
Write for a busy manager, in plain words:
- headline: one sentence, under 25 words, saying what changed and by how much, e.g.
  "Advertiser 3476 showed no ads from 11:00 on 12 June, against about 20,549 an hour usually."
  Write times as 11:00 (never "hour 11"), the date as {day_label}, and metrics as impressions, spend,
  CPM and CTR. Use the numbers exactly as they appear in DATA (value, usual, change_pct).
- drivers: 1 to 3 short points on what the data shows behind it: which metrics moved, whether the
  whole day moved or only these hours, the last hour with ads, and which ad exchanges changed most
  that day. Only state what DATA shows. If DATA does not show a cause, say what changed, not why.
- confidence: "high" if the change is large and shows in several numbers, "medium" if it shows in
  one metric only, "low" if the hours have little volume."""

# The 4 fixed queries. %(a)s advertiser, %(d)s day, %(s)s first hour, %(e)s last hour.
# advertiser_id and report_date are cast (::int, ::date): the first version of daily_campaign stored
# them as text, and Postgres won't compare text with a number.
QUERIES = {
    "flags": """
        SELECT hour || ':00' AS time, metric,
               CASE metric WHEN 'ctr' THEN 'CTR in percent' WHEN 'cpm' THEN 'CPM' WHEN 'spend' THEN 'spend'
                           ELSE 'impressions' END AS shown_as,
               ROUND((CASE WHEN metric = 'ctr' THEN 100 * value ELSE value END)::numeric,
                     CASE metric WHEN 'ctr' THEN 3 WHEN 'impressions' THEN 0 ELSE 1 END) AS value,
               ROUND((CASE WHEN metric = 'ctr' THEN 100 * baseline ELSE baseline END)::numeric,
                     CASE metric WHEN 'ctr' THEN 3 WHEN 'impressions' THEN 0 ELSE 1 END) AS usual,
               ROUND((100 * change)::numeric) AS change_pct, ROUND(z::numeric, 1) AS z
        FROM anomalies
        WHERE advertiser_id::int = %(a)s::int AND report_date::date = %(d)s::date AND hour BETWEEN %(s)s AND %(e)s
        ORDER BY hour, metric""",
    "hours_vs_usual": """
        SELECT hour || ':00' AS time,
               SUM(impressions) FILTER (WHERE report_date::date = %(d)s::date) AS impressions,
               ROUND(AVG(impressions) FILTER (WHERE report_date::date <> %(d)s::date)) AS usual_impressions,
               ROUND(SUM(total_cost) FILTER (WHERE report_date::date = %(d)s::date), 1) AS spend,
               ROUND(AVG(total_cost) FILTER (WHERE report_date::date <> %(d)s::date), 1) AS usual_spend,
               ROUND(100.0 * SUM(clicked_impressions) FILTER (WHERE report_date::date = %(d)s::date)
                     / NULLIF(SUM(impressions) FILTER (WHERE report_date::date = %(d)s::date), 0), 3) AS ctr_pct,
               ROUND(100.0 * SUM(clicked_impressions) FILTER (WHERE report_date::date <> %(d)s::date)
                     / NULLIF(SUM(impressions) FILTER (WHERE report_date::date <> %(d)s::date), 0), 3) AS usual_ctr_pct
        FROM hourly_pacing
        WHERE advertiser_id::int = %(a)s::int AND hour BETWEEN %(s)s AND %(e)s
        GROUP BY hour ORDER BY hour""",
    "day_vs_usual": """
        SELECT (SELECT MAX(hour) FROM hourly_pacing
                WHERE advertiser_id::int = %(a)s::int AND report_date::date = %(d)s::date AND impressions > 0) AS last_hour_with_ads,
               SUM(impressions) FILTER (WHERE report_date::date = %(d)s::date) AS day_impressions,
               ROUND(AVG(impressions) FILTER (WHERE report_date::date <> %(d)s::date)) AS usual_day_impressions,
               ROUND(SUM(total_cost) FILTER (WHERE report_date::date = %(d)s::date), 1) AS day_spend,
               ROUND(AVG(total_cost) FILTER (WHERE report_date::date <> %(d)s::date), 1) AS usual_day_spend
        FROM daily_campaign WHERE advertiser_id::int = %(a)s::int""",
    "exchanges_that_day": """
        WITH x AS (
            SELECT ad_exchange, report_date, SUM(wins) AS wins
            FROM daily_auction WHERE advertiser_id::int = %(a)s::int
            GROUP BY ad_exchange, report_date),
        y AS (
            SELECT ad_exchange,
                   COALESCE(SUM(wins) FILTER (WHERE report_date::date = %(d)s::date), 0) AS impressions_that_day,
                   ROUND(AVG(wins) FILTER (WHERE report_date::date <> %(d)s::date)) AS usual_impressions_per_day
            FROM x GROUP BY ad_exchange)
        SELECT ad_exchange, impressions_that_day, usual_impressions_per_day,
               ROUND(100.0 * (impressions_that_day - usual_impressions_per_day)
                     / NULLIF(usual_impressions_per_day, 0)) AS change_pct
        FROM y
        ORDER BY ABS(impressions_that_day - usual_impressions_per_day) DESC NULLS LAST
        LIMIT 5""",
}


def events_from(flags):
    """Group flags (advertiser, date, hour, metric, value, baseline, z) into events of neighbouring hours."""
    by_day = defaultdict(list)
    for f in flags:
        by_day[(f[0], f[1])].append(f)
    events = []
    for (adv, day), fs in by_day.items():
        hours = sorted({f[2] for f in fs})
        start = prev = hours[0]
        for h in hours[1:] + [None]:
            if h is not None and h == prev + 1:
                prev = h
                continue
            mine = [f for f in fs if start <= f[2] <= prev]
            key = json.dumps(sorted([f[2], f[3], round(f[4], 6), round(f[5], 6)] for f in mine))
            events.append({"advertiser_id": adv, "report_date": day, "start": start, "end": prev,
                           "strength": max(abs(f[6]) for f in mine), "flags": len(mine),
                           "fingerprint": hashlib.sha1(key.encode()).hexdigest()[:16]})
            if h is not None:
                start = prev = h
    events.sort(key=lambda e: -e["strength"])
    return events


def facts_for(e):
    params = {"a": e["advertiser_id"], "d": e["report_date"], "s": e["start"], "e": e["end"]}
    data = {}
    for name, sql in QUERIES.items():
        r = llm.query(sql, params)
        # show the SQL with the values filled in, so anyone can re-run it
        r["sql"] = " ".join(sql.split()).replace("%(a)s", str(e["advertiser_id"])) \
            .replace("%(d)s", f"'{e['report_date']}'").replace("%(s)s", str(e["start"])) \
            .replace("%(e)s", str(e["end"]))
        data[name] = r
    return data


def hours_label(e):
    return f"at {e['start']:02d}:00" if e["start"] == e["end"] else f"from {e['start']:02d}:00 to {e['end']:02d}:59"


def run(max_explain=MAX_EXPLAIN, dry_run=False, quiet=False, redo=False):
    if not DATABASE_URL:
        raise SystemExit("NEON_DATABASE_URL was not found in .env")
    with psycopg.connect(DATABASE_URL, connect_timeout=30) as con:
        con.execute(llm.AI_SCHEMA.read_text())
        flags = con.execute("""SELECT advertiser_id, report_date, hour, metric, value, baseline, z
                               FROM anomalies""").fetchall()
        done = dict(con.execute("""SELECT advertiser_id || '|' || report_date || '|' || hour, fingerprint
                                   FROM explanations""").fetchall())
        events = events_from(flags)
        current = {f"{e['advertiser_id']}|{e['report_date']}|{e['start']}" for e in events}
        if not dry_run:  # explanations of events that no longer exist
            for key in set(done) - current:
                a, d, h = key.split("|")
                con.execute("DELETE FROM explanations WHERE advertiser_id = %s AND report_date = %s AND hour = %s",
                            (a, d, h))
            con.commit()

    todo = [e for e in events
            if redo or done.get(f"{e['advertiser_id']}|{e['report_date']}|{e['start']}") != e["fingerprint"]]
    if not quiet:
        print(f"Events: {len(events)} ({len(flags)} flags grouped); {len(events) - len(todo)} already explained, "
              f"{len(todo)} to explain, this run explains up to {max_explain}")
    passed = withheld = 0
    for e in todo[:max_explain]:
        label = f"{e['advertiser_id']} {e['report_date']} {hours_label(e)}"
        data = facts_for(e)
        if dry_run:
            print(f"\n== {label}  (strongest z {e['strength']:.1f}, {e['flags']} flags)")
            for name, r in data.items():
                print(f"  {name}: {r['columns']}")
                for row in r["rows"][:6]:
                    print(f"    {row}")
            continue
        day = e["report_date"]
        day_label = f"{day.day} {day:%B}" if hasattr(day, "day") else str(day)
        task = TASK.format(adv=e["advertiser_id"], day_label=day_label, hours=hours_label(e))
        result = llm.grounded(task, data, SCHEMA, purpose="what_changed")
        out = result["output"] or {}
        with psycopg.connect(DATABASE_URL, connect_timeout=30) as con:
            con.execute("""
                INSERT INTO explanations (advertiser_id, report_date, hour, end_hour, fingerprint, status,
                                          headline, drivers, confidence, note, facts, sql, provider, run_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (advertiser_id, report_date, hour) DO UPDATE SET
                    end_hour = EXCLUDED.end_hour, fingerprint = EXCLUDED.fingerprint,
                    status = EXCLUDED.status, headline = EXCLUDED.headline, drivers = EXCLUDED.drivers,
                    confidence = EXCLUDED.confidence, note = EXCLUDED.note, facts = EXCLUDED.facts,
                    sql = EXCLUDED.sql, provider = EXCLUDED.provider, run_id = EXCLUDED.run_id,
                    created_at = now()""",
                (e["advertiser_id"], e["report_date"], e["start"], e["end"], e["fingerprint"],
                 result["status"], out.get("headline"), json.dumps(out.get("drivers")),
                 out.get("confidence"), result["note"], json.dumps(data, default=str),
                 json.dumps(result["sql"]), result["provider"], result["run_id"]))
        if result["status"] == "pass":
            passed += 1
            if not quiet:
                print(f"  PASS     {label}: {out['headline']}")
        else:
            withheld += 1
            if not quiet:
                print(f"  WITHHELD {label}: {result['note']}")
    if not quiet and not dry_run:
        print(f"Done: {passed} explained, {withheld} withheld, {max(len(todo) - max_explain, 0)} left for the next run")
    return passed, withheld


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Explain the unusual hours (What changed tab)")
    parser.add_argument("--max", type=int, default=MAX_EXPLAIN, help="most events to explain this run")
    parser.add_argument("--dry-run", action="store_true", help="show events and their data; no AI calls")
    parser.add_argument("--redo", action="store_true", help="explain again even if already explained")
    args = parser.parse_args()
    run(max_explain=args.max, dry_run=args.dry_run, redo=args.redo)