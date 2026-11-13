"""
Tick: the hourly pipeline. Each run processes the next hour of data and moves the watermark.

    python pipeline/src/pipeline/tick.py              # the next hour
    python pipeline/src/pipeline/tick.py --hours 6    # the next 6 hours in one go
    python pipeline/src/pipeline/tick.py --all        # everything not processed yet (catch up)
    python pipeline/src/pipeline/tick.py --rebuild    # rebuild and reload every hour (run.py uses this)
    python pipeline/src/pipeline/tick.py --status     # where the watermark is
    python pipeline/src/pipeline/tick.py --reset --yes
        # start the replay again from the first hour: forgets the watermark and empties the
        # daily tables in Neon, so the dashboard fills up again hour by hour

The watermark is a bookmark: "every hour up to and including this one is processed". It is kept
in data/processed/warehouse.duckdb (table pipeline_watermark) and in Neon (pipeline_status).

One tick:
  1. Read the watermark, find the next hour that has files (ingest.py makes one file per hour).
  2. Make the pipeline see only the hours up to that one (clean.py: raw views + checks).
  3. Rebuild the model (model.py). Clicks and conversions that arrive late are linked to
     their earlier impressions here.
  4. Send Neon only the days that changed: the new hour's day, the days of the impressions that
     this hour's clicks and conversions belong to, and the day before (late links).
  5. Only when all that worked, move the watermark.

Idempotent: if a tick fails halfway, the watermark has not moved and the next tick redoes the
same hour. If there is no new hour, a tick does nothing. Running it twice never doubles anything.

The iPinYou logs are from 2013, so "the next hour" is the next hour of the 2013 data: the
pipeline replays the week as if it were arriving live. The scheduler (compose.yaml) runs a tick
on a timer.
"""

import argparse
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import duckdb

import clean
import model


PROJECT_ROOT = Path(__file__).resolve().parents[3]
WAREHOUSE = Path("data/processed/warehouse.duckdb")
LOGS = ["imp", "clk", "conv", "bid", "bid_summary"]


# ---- Watermark ---------------------------------------------------------------

def get_watermark(con):
    """The last hour processed, as 'YYYYMMDDHH', or None if nothing was processed yet."""
    con.execute("""
        CREATE TABLE IF NOT EXISTS pipeline_watermark (
            processed_up_to VARCHAR,          -- last hour processed, YYYYMMDDHH
            updated_at TIMESTAMP DEFAULT current_timestamp
        )
    """).fetchall()
    row = con.execute("SELECT processed_up_to FROM pipeline_watermark").fetchall()
    return row[0][0] if row else None


def set_watermark(con, hour):
    get_watermark(con)
    con.execute("DELETE FROM pipeline_watermark").fetchall()
    if hour is not None:
        con.execute("INSERT INTO pipeline_watermark (processed_up_to) VALUES (?)", [hour]).fetchall()


def start_of(hour):
    return datetime.strptime(hour, "%Y%m%d%H")


def end_of(hour):
    """'2013060714' -> 2013-06-07 15:00 (the hour 14:00-15:00 is complete)."""
    return start_of(hour) + timedelta(hours=1)


def label(hour):
    return "nothing yet" if hour is None else f"{start_of(hour):%Y-%m-%d %H}:00-{end_of(hour):%H}:00"


# ---- Which hours exist and which days changed ------------------------------------

def available_hours():
    """Every hour that has at least one file, in any log."""
    return sorted({clean.hour_of(f) for log in LOGS for f in clean.arrived_files(log)})


def changed_days(con, after, up_to):
    """The report days a tick must send to Neon: those of the events that arrived in
    (after, up_to], plus the day before the newest hour (clicks linked late)."""
    low = end_of(after) if after else datetime(1970, 1, 1)
    high = end_of(up_to)
    params = [low, high] * 4
    rows = con.execute("""
        SELECT impression_date FROM fact_impressions
            WHERE impression_datetime >= ? AND impression_datetime < ?
        UNION SELECT report_date FROM fact_clicks
            WHERE click_datetime >= ? AND click_datetime < ?
        UNION SELECT report_date FROM fact_conversions
            WHERE conversion_datetime >= ? AND conversion_datetime < ?
        UNION SELECT bid_date FROM stg_bid_summary
            WHERE bid_date + hour * INTERVAL 1 HOUR >= ? AND bid_date + hour * INTERVAL 1 HOUR < ?
    """, params).fetchall()
    days = {r[0] for r in rows if r[0] is not None}
    day_before = (start_of(up_to) - timedelta(days=1)).date()
    if con.execute("SELECT COUNT(*) FROM dim_date WHERE date = ?", [day_before]).fetchall()[0][0]:
        days.add(day_before)
    return sorted(days)


def arrived_counts(con, after, up_to):
    low = end_of(after) if after else datetime(1970, 1, 1)
    high = end_of(up_to)
    return con.execute("""
        SELECT
            (SELECT COUNT(*) FROM fact_impressions WHERE impression_datetime >= $1 AND impression_datetime < $2),
            (SELECT COUNT(*) FROM fact_clicks WHERE click_datetime >= $1 AND click_datetime < $2),
            (SELECT COUNT(*) FROM fact_conversions WHERE conversion_datetime >= $1 AND conversion_datetime < $2)
    """, [low, high]).fetchall()[0]


# ---- One tick -------------------------------------------------------------------

def process(con, watermark, target, quiet=True):
    """Steps 1-3 of a tick, in DuckDB only: make the hours up to target visible, check them,
    rebuild the model. Returns the days to send to Neon and the counts that arrived."""
    clean.prepare(con, up_to=target, quiet=quiet)
    model.build(con, quiet=quiet)
    problems = model.check(con, quiet=quiet)
    if problems:
        raise SystemExit("Model check failed: " + ", ".join(problems) + ". Watermark not moved.")
    return changed_days(con, watermark, target), arrived_counts(con, watermark, target)


def tick(hours=1, catch_up=False, rebuild=False):
    """Process the next `hours` hours (or all pending hours). Returns the new watermark.
    rebuild=True starts from the first hour again: everything is rebuilt and reloaded."""
    start = time.time()
    WAREHOUSE.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(WAREHOUSE))
    watermark = None if rebuild else get_watermark(con)
    catch_up = catch_up or rebuild
    pending = [h for h in available_hours() if watermark is None or h > watermark]
    if not pending:
        con.close()
        print(f"Up to date: watermark {label(watermark)}. Nothing new to process.")
        return watermark

    target = pending[-1] if catch_up else pending[min(hours, len(pending)) - 1]
    quiet = not catch_up
    print(f"Tick: {label(pending[0])}" + (f" to {label(target)}" if target != pending[0] else ""), flush=True)

    # 1-3. Only the hours up to target are visible; checks; full model rebuild
    try:
        days, (impressions, clicks, conversions) = process(con, watermark, target, quiet)
    finally:
        con.close()  # load.py opens the warehouse read-only

    # 4. Send the changed days to Neon (load.py needs NEON_DATABASE_URL)
    import load
    load.load(dates=days, processed_up_to=end_of(target),
              mode="catch-up" if catch_up else "hourly", quiet=quiet)

    # 5. Everything worked: move the watermark
    con = duckdb.connect(str(WAREHOUSE))
    set_watermark(con, target)
    con.close()

    left = len([h for h in pending if h > target])
    print(f"  arrived: {impressions:,} impressions, {clicks:,} clicks, {conversions:,} conversions")
    print(f"  sent to Neon: {len(days)} day(s) ({', '.join(f'{d:%d %b}' for d in days)})")
    print(f"  watermark: {label(target)} · {left} hour(s) still to come · {time.time() - start:.0f}s")
    return target


def status():
    con = duckdb.connect(str(WAREHOUSE))
    watermark = get_watermark(con)
    con.close()
    hours = available_hours()
    pending = [h for h in hours if watermark is None or h > watermark]
    print(f"Watermark: {label(watermark)}")
    print(f"Hours with files: {len(hours)}" + (f" ({label(hours[0])} to {label(hours[-1])})" if hours else ""))
    print(f"Hours still to process: {len(pending)}")


def reset():
    """Start the replay again: forget the watermark and empty the daily tables in Neon."""
    con = duckdb.connect(str(WAREHOUSE))
    set_watermark(con, None)
    con.close()
    import load
    import psycopg
    with psycopg.connect(load.DATABASE_URL) as neon:
        with neon.transaction():
            neon.execute(load.SCHEMA.read_text())
            for table in ["daily_campaign", "daily_auction", "hourly_pacing"]:
                neon.execute(f"DELETE FROM {table}")
            neon.execute("DELETE FROM pipeline_status")
    print("Replay reset: watermark cleared, daily tables in Neon emptied. "
          "The next tick processes the first hour.")


if __name__ == "__main__":
    os.chdir(PROJECT_ROOT)
    parser = argparse.ArgumentParser(description="Process the next hour(s) of data")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--hours", type=int, default=1, help="hours to process in this tick (default 1)")
    group.add_argument("--all", action="store_true", help="process every hour not done yet")
    group.add_argument("--rebuild", action="store_true", help="rebuild and reload every hour")
    group.add_argument("--status", action="store_true", help="show the watermark and stop")
    group.add_argument("--reset", action="store_true", help="start the replay again (needs --yes)")
    parser.add_argument("--yes", action="store_true", help="confirm --reset")
    args = parser.parse_args()

    try:
        if args.status:
            status()
        elif args.reset:
            if not args.yes:
                raise SystemExit("--reset empties the daily tables in Neon. Add --yes to confirm.")
            reset()
        else:
            tick(hours=max(args.hours, 1), catch_up=args.all, rebuild=args.rebuild)
    except clean.DataQualityError as error:
        print(f"{error}. Watermark not moved.")
        sys.exit(1)
    except Exception as error:  # e.g. Neon cannot be reached
        if type(error).__module__.startswith("psycopg"):
            print(f"Could not load into Neon ({type(error).__name__}: {str(error).splitlines()[0]}). "
                  "Watermark not moved: the same hour is tried again next tick.")
            sys.exit(1)
        raise