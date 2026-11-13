"""
Load: copy the finished tables from DuckDB to Neon Postgres.

    python pipeline/src/pipeline/load.py

model.py builds the tables in data/processed/warehouse.duckdb; this script reads them
(read-only) and sends them to Neon:

    dim_advertiser, dim_campaign, dim_date     replaced completely
    daily_campaign, daily_auction, hourly_pacing
        the days in this load are deleted, then inserted again

Run on its own it loads every day. An hourly tick (tick.py) calls load(dates=...) with only the
days that changed in that hour, and processed_up_to, the watermark, which is saved in
pipeline_status so the dashboard can show how far the data goes.

Each table is loaded in one transaction: if anything fails, Neon keeps the old rows.
Running it twice is safe: the numbers never double.
"""

import os
from pathlib import Path

import duckdb
import psycopg
from dotenv import load_dotenv


# Find the project root directory
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Make relative file paths work from the project root
os.chdir(PROJECT_ROOT)

# Load environment variables
load_dotenv(PROJECT_ROOT / ".env")

DATABASE_URL = os.getenv("NEON_DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("NEON_DATABASE_URL was not found in .env")

WAREHOUSE = Path("data/processed/warehouse.duckdb")
SCHEMA = Path("pipeline/sql/neon/schema.sql")

# table -> columns to send, in this order
TABLES = {
    "dim_advertiser": ["advertiser_id", "industry", "advertiser_name"],
    "dim_campaign": ["campaign_id", "advertiser_id", "campaign_name", "season",
                     "first_date", "last_date", "days_live", "has_bid_logs"],
    "dim_date": ["date", "weekday", "day_of_week", "is_weekend", "label"],
    "daily_campaign": ["advertiser_id", "report_date", "impressions", "clicks", "conversions",
                       "total_cost", "clicked_impressions", "converted_impressions",
                       "post_click_conversions", "post_view_conversions"],
    "daily_auction": ["advertiser_id", "report_date", "ad_exchange", "floor_band", "bids", "wins",
                      "sum_bid_price", "sum_bid_price_won", "sum_paying_price", "sum_floor_price",
                      "floor_set_price", "paid_above_bid", "paid_below_floor"],
    "hourly_pacing": ["advertiser_id", "report_date", "hour", "bids", "impressions",
                      "clicked_impressions", "converted_impressions", "total_cost"],
}

DIMENSIONS = {"dim_advertiser", "dim_campaign", "dim_date"}


def read_tables(dates=None):
    """Read every table to send from the DuckDB warehouse (only the given days, if any)."""
    if not WAREHOUSE.exists():
        raise SystemExit(f"{WAREHOUSE} not found: run clean.py and model.py first")
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    data = {}
    for name, columns in TABLES.items():
        sql = f"SELECT {', '.join(columns)} FROM {name}"
        if dates is not None and name not in DIMENSIONS:
            sql += " WHERE report_date IN (SELECT UNNEST(?::DATE[]))"
            data[name] = con.execute(sql, [[str(d) for d in dates]]).fetchall()
        else:
            data[name] = con.execute(sql).fetchall()
    if dates is None:
        dates = [r[0] for r in con.execute("SELECT DISTINCT report_date FROM daily_campaign").fetchall()]
    con.close()
    return data, sorted(dates)


def load_table(cursor, name, columns, rows, dates):
    if name in DIMENSIONS:
        # Small tables: replace everything
        cursor.execute(f"DELETE FROM {name}")
    else:
        # Delete the days we are about to insert, so a rerun never doubles
        cursor.execute(f"DELETE FROM {name} WHERE report_date = ANY(%s)", (dates,))

    placeholders = ", ".join(["%s"] * len(columns))
    cursor.executemany(
        f"INSERT INTO {name} ({', '.join(columns)}) VALUES ({placeholders})",
        rows,
    )
    cursor.execute(
        "INSERT INTO load_log (table_name, rows_loaded) VALUES (%s, %s)", (name, len(rows))
    )


def load(dates=None, processed_up_to=None, mode="batch", quiet=False):
    """Send the warehouse tables to Neon. dates: only these days (None = every day).
    processed_up_to: the watermark to save in pipeline_status."""
    data, dates = read_tables(dates)

    with psycopg.connect(DATABASE_URL) as neon_conn:

        # Create or update the tables
        with neon_conn.transaction():
            neon_conn.execute(SCHEMA.read_text())

        for name, columns in TABLES.items():
            # One transaction per table: all rows or none
            with neon_conn.transaction(), neon_conn.cursor() as cursor:
                load_table(cursor, name, columns, data[name], dates)
            if not quiet:
                print(f"  {name:<16} {len(data[name]):>6,} rows loaded")

        if processed_up_to is not None:
            with neon_conn.transaction():
                neon_conn.execute(
                    """
                    INSERT INTO pipeline_status (id, processed_up_to, mode, updated_at)
                    VALUES (1, %s, %s, now())
                    ON CONFLICT (id) DO UPDATE SET processed_up_to = EXCLUDED.processed_up_to,
                        mode = EXCLUDED.mode, updated_at = now()
                    """,
                    (processed_up_to, mode),
                )

    if not quiet:
        print("Successfully loaded all tables into Neon.")
    return {name: len(rows) for name, rows in data.items()}


if __name__ == "__main__":
    load()