"""
Model: build the data model in DuckDB from the staging views.

    python pipeline/src/pipeline/model.py

Runs the SQL files in this order (each file is one SELECT; the file name is the table name):

    1. pipeline/sql/intermediate  clicks/conversions linked to impressions, user agents
    2. pipeline/sql/facts         fact_impressions, fact_clicks, fact_conversions, fact_bids
    3. pipeline/sql/dimensions    dim_advertiser, dim_campaign, dim_date
    4. pipeline/sql/marts         daily_campaign, daily_auction, hourly_pacing (sent to Neon)

Everything is stored in data/processed/warehouse.duckdb (clean.py must run first: it creates
the staging views). The two biggest facts are VIEWS, so the warehouse file stays small.
At the end the numbers are checked: the daily tables must add up to the fact tables.
"""

import os
import sys
import time
from pathlib import Path

import duckdb


# Find the project root directory and make relative paths work from there
PROJECT_ROOT = Path(__file__).resolve().parents[3]
WAREHOUSE = Path("data/processed/warehouse.duckdb")
SQL_DIR = PROJECT_ROOT / "pipeline" / "sql"

FOLDERS = ["intermediate", "facts", "dimensions", "marts"]

# Stored as views (computed when read) instead of tables, to save disk:
# fact_impressions has one row per impression (millions), fact_bids even more.
VIEWS = {"fact_impressions", "fact_bids"}


def drop_if_exists(con, name):
    """Drop a table or a view with this name (DuckDB needs the right DROP for each)."""
    kind = con.execute(
        "SELECT table_type FROM information_schema.tables WHERE table_name = ?", [name]
    ).fetchall()
    if kind:
        con.execute(f"DROP {'VIEW' if kind[0][0] == 'VIEW' else 'TABLE'} {name}").fetchall()


def build(con, sql_dir=SQL_DIR, quiet=False):
    """Build every model, folder by folder, file by file (sorted by name)."""
    for folder in FOLDERS:
        for sql_file in sorted((Path(sql_dir) / folder).glob("*.sql")):
            name = sql_file.stem
            sql = sql_file.read_text().strip().rstrip(";")
            kind = "VIEW" if name in VIEWS else "TABLE"
            start = time.time()
            drop_if_exists(con, name)
            con.execute(f"CREATE {kind} {name} AS {sql}").fetchall()
            rows = con.execute(f"SELECT COUNT(*) FROM {name}").fetchall()[0][0] if kind == "TABLE" else None
            size = f"{rows:,} rows" if rows is not None else "view"
            if not quiet:
                print(f"  {folder + '/' + name:<38} {size:>16}  ({time.time() - start:.1f}s)")


def check(con, quiet=False):
    """The daily tables must add up to the fact tables. Returns a list of problems."""
    problems = []
    comparisons = [
        ("impressions",
         "SELECT COUNT(*) FROM fact_impressions",
         "SELECT SUM(impressions) FROM daily_campaign"),
        ("clicks",
         "SELECT COUNT(*) FROM fact_clicks",
         "SELECT SUM(clicks) FROM daily_campaign"),
        ("conversions",
         "SELECT COUNT(*) FROM fact_conversions",
         "SELECT SUM(conversions) FROM daily_campaign"),
        ("impressions in fact = staging",
         "SELECT COUNT(*) FROM stg_impressions",
         "SELECT COUNT(*) FROM fact_impressions"),
        ("wins in daily_auction",
         "SELECT COUNT(*) FROM fact_impressions",
         "SELECT SUM(wins) FROM daily_auction"),
        ("bids in daily_auction",
         "SELECT SUM(bids) FROM stg_bid_summary",
         "SELECT SUM(bids) FROM daily_auction"),
        ("impressions in hourly_pacing",
         "SELECT SUM(impressions) FROM daily_campaign",
         "SELECT SUM(impressions) FROM hourly_pacing"),
        ("cost in hourly_pacing",
         "SELECT SUM(total_cost) FROM daily_campaign",
         "SELECT SUM(total_cost) FROM hourly_pacing"),
        ("advertisers in dim_campaign",
         "SELECT COUNT(DISTINCT advertiser_id) FROM fact_impressions",
         "SELECT COUNT(*) FROM dim_campaign"),
    ]
    if not quiet:
        print()
    for name, fact_sql, mart_sql in comparisons:
        fact_value = con.execute(fact_sql).fetchall()[0][0] or 0
        mart_value = con.execute(mart_sql).fetchall()[0][0] or 0
        ok = fact_value == mart_value
        if not quiet or not ok:
            print(f"  {name:<32} {fact_value:>14,} = {mart_value:<14,} {'OK' if ok else 'MISMATCH'}")
        if not ok:
            problems.append(name)

    # Funnel: a clicked impression must be an impression, a conversion needs an impression
    bad_funnel = con.execute(
        "SELECT COUNT(*) FROM daily_campaign WHERE clicks > impressions OR conversions > impressions"
    ).fetchall()[0][0]
    if not quiet or bad_funnel:
        print(f"  {'days with more clicks than impressions':<32} {bad_funnel:>14,}   {'OK' if bad_funnel == 0 else 'PROBLEM'}")
    if bad_funnel:
        problems.append("funnel")
    return problems


def model():
    os.chdir(PROJECT_ROOT)
    if not WAREHOUSE.exists():
        raise SystemExit(f"{WAREHOUSE} not found: run clean.py first")

    start = time.time()
    con = duckdb.connect(str(WAREHOUSE))
    build(con)
    problems = check(con)
    con.close()

    if problems:
        print("\nModel check FAILED: " + ", ".join(problems))
        sys.exit(1)
    print(f"\nModel built and checked ({time.time() - start:.0f}s).")


if __name__ == "__main__":
    model()