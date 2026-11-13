"""
Clean: build the staging views in DuckDB and check the data before anything is loaded.

    python pipeline/src/pipeline/clean.py

What it does:
* Opens (or creates) data/processed/warehouse.duckdb.
* Creates one raw_<log> view per log over the hourly Parquet files in data/interim.
  The batch run uses every hour; an hourly tick (tick.py) uses only the hours up to its
  watermark, so the rest of the pipeline sees exactly the data that has "arrived".
* Creates one view per file in pipeline/sql/staging (stg_impressions, stg_clicks, ...).
  Views store no data: they read the Parquet files when queried, so the warehouse file stays small.
* Runs data quality checks and prints them as a table. The results are also saved to
  reports/pipeline_data_quality.csv.
* Stops with an error if a FAIL check fails, so bad data never reaches Neon.
"""

import csv
import os
import sys
from pathlib import Path

import duckdb
from dotenv import load_dotenv

from ingest import COLUMNS, SUMMARY_KEYS


# Find the project root directory
PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")

WAREHOUSE = Path("data/processed/warehouse.duckdb")
STAGING_DIR = PROJECT_ROOT / "pipeline" / "sql" / "staging"
REPORT = Path("reports/pipeline_data_quality.csv")
INTERIM_DIR = Path("data/interim")

# raw view -> (folder, columns). Every column is text, as ingest.py saved it.
RAW_LOGS = {
    "imp": COLUMNS["imp"] + ["source_file"],
    "clk": COLUMNS["clk"] + ["source_file"],
    "conv": COLUMNS["conv"] + ["source_file"],
    "bid": COLUMNS["bid"] + ["source_file"],
    "bid_summary": SUMMARY_KEYS + ["bids", "sum_bidding_price"],
}


class DataQualityError(Exception):
    pass


def hour_of(path):
    """imp_20130606_2013060614.parquet -> '2013060614'"""
    return path.stem.rsplit("_", 1)[1]


def arrived_files(log, up_to=None):
    """The hourly files of a log, all of them, or only up to and including the hour up_to
    ('YYYYMMDDHH')."""
    files = sorted((INTERIM_DIR / log).glob(f"{log}_*_*.parquet"))
    return [f for f in files if up_to is None or hour_of(f) <= up_to]


def create_raw_views(con, up_to=None):
    """raw_imp, raw_clk, raw_conv, raw_bid, raw_bid_summary over the files that have arrived.
    A log with no files yet gets an empty view with the right columns."""
    for log, columns in RAW_LOGS.items():
        files = arrived_files(log, up_to)
        if files:
            listing = ", ".join(f"'{f.as_posix()}'" for f in files)
            sql = f"SELECT * FROM read_parquet([{listing}], union_by_name = true)"
        else:
            types = {"bids": "BIGINT", "sum_bidding_price": "BIGINT"}
            sql = "SELECT " + ", ".join(f"CAST(NULL AS {types.get(c, 'VARCHAR')}) AS {c}" for c in columns) \
                + " WHERE false"
        con.execute(f"CREATE OR REPLACE VIEW raw_{log} AS {sql}").fetchall()


# Each check: (name, severity, SQL that returns one number, what a problem looks like)
#   FAIL = stop the pipeline when the number is not 0
#   WARN = report it, keep going
#   INFO = just a number worth knowing
# Checks whose name ends in "loaded" are the other way round: the number is a row count,
# and the problem is when it is 0.
CHECKS = [
    ("impressions loaded", "FAIL",
     "SELECT COUNT(*) FROM stg_impressions",
     "no impressions at all"),
    ("days with impressions", "INFO",
     "SELECT COUNT(DISTINCT impression_date) FROM stg_impressions",
     ""),
    ("advertisers with impressions", "INFO",
     "SELECT COUNT(DISTINCT advertiser_id) FROM stg_impressions",
     ""),
    ("advertisers with bids", "INFO",
     "SELECT COUNT(DISTINCT advertiser_id) FROM stg_bids",
     ""),
    ("advertisers in the bid summary", "INFO",
     "SELECT COUNT(DISTINCT advertiser_id) FROM stg_bid_summary",
     ""),
    ("impression timestamps that did not parse", "FAIL",
     "SELECT COUNT(*) FROM stg_impressions WHERE impression_datetime IS NULL",
     "rows with a broken timestamp"),
    ("click timestamps that did not parse", "FAIL",
     "SELECT COUNT(*) FROM stg_clicks WHERE click_datetime IS NULL",
     "rows with a broken timestamp"),
    ("impressions without a paying price", "WARN",
     "SELECT COUNT(*) FROM stg_impressions WHERE paying_price IS NULL",
     "cost would be missing"),
    ("duplicate impressions removed", "INFO",
     "SELECT (SELECT COUNT(*) FROM raw_imp)"
     " - (SELECT COUNT(*) FROM stg_impressions)",
     ""),
    ("duplicate clicks removed", "INFO",
     "SELECT (SELECT COUNT(*) FROM raw_clk)"
     " - (SELECT COUNT(*) FROM stg_clicks)",
     ""),
    ("clicks with no matching impression", "WARN",
     "SELECT COUNT(*) FROM stg_clicks c WHERE NOT EXISTS ("
     " SELECT 1 FROM stg_impressions i WHERE i.bid_id = c.bid_id)",
     "a click we cannot link to an impression"),
    ("conversions with no matching impression", "WARN",
     "SELECT COUNT(*) FROM stg_conversions v WHERE NOT EXISTS ("
     " SELECT 1 FROM stg_impressions i WHERE i.bid_id = v.bid_id)",
     "a conversion we cannot link to an impression"),
    ("clicks loaded", "INFO",
     "SELECT COUNT(*) FROM stg_clicks",
     ""),
    ("conversions loaded", "INFO",
     "SELECT COUNT(*) FROM stg_conversions",
     ""),
    ("more clicks than impressions", "FAIL",
     "SELECT CASE WHEN (SELECT COUNT(*) FROM stg_clicks)"
     " > (SELECT COUNT(*) FROM stg_impressions) THEN 1 ELSE 0 END",
     "the funnel is upside down"),
    ("impressions paid above the bid", "WARN",
     "SELECT COUNT(*) FROM stg_impressions WHERE paying_price > bidding_price",
     "a second-price auction should never charge more than the bid"),
    ("impressions paid below the floor price", "WARN",
     "SELECT COUNT(*) FROM stg_impressions WHERE paying_price < ad_slot_floor_price",
     "the floor is the minimum price"),
    ("bids loaded", "WARN",
     "SELECT COUNT(*) FROM stg_bids",
     "no bid logs: win rate cannot be computed"),
]


def create_staging_views(con, sql_dir=STAGING_DIR, quiet=False):
    for sql_file in sorted(Path(sql_dir).glob("stg_*.sql")):
        sql = sql_file.read_text().strip().rstrip(";")
        con.execute(f"CREATE OR REPLACE VIEW {sql_file.stem} AS {sql}").fetchall()
        if not quiet:
            print(f"Created view: {sql_file.stem}")


def run_checks(con):
    results = []
    for name, severity, sql, problem in CHECKS:
        value = con.execute(sql).fetchall()[0][0] or 0
        problem_found = (value == 0) if name.endswith("loaded") else (value != 0)
        if severity == "INFO":
            status = "INFO"
        elif not problem_found:
            status = "PASS"
        else:
            status = severity
        results.append({"check": name, "severity": severity, "value": value,
                        "status": status, "means": problem if status in ("FAIL", "WARN") else ""})
    return results


def print_results(results):
    print()
    print(f"{'check':<44}{'value':>12}  status")
    print("-" * 66)
    for r in results:
        print(f"{r['check']:<44}{r['value']:>12,}  {r['status']}")
    print()


def save_results(results):
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with REPORT.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["check", "severity", "value", "status", "means"])
        writer.writeheader()
        writer.writerows(results)
    print(f"Saved {REPORT}")


def prepare(con, up_to=None, quiet=False):
    """Raw views, staging views and checks. Raises DataQualityError on a FAIL.
    quiet=True (hourly ticks) prints only the checks that did not pass."""
    create_raw_views(con, up_to)
    create_staging_views(con, quiet=quiet)
    results = run_checks(con)
    if quiet:
        for r in results:
            if r["status"] in ("FAIL", "WARN"):
                print(f"  {r['status']}: {r['check']} = {r['value']:,}")
    else:
        print_results(results)
        save_results(results)
    failed = [r["check"] for r in results if r["status"] == "FAIL"]
    if failed:
        raise DataQualityError("Data quality FAILED: " + "; ".join(failed))
    return results


def clean():
    os.chdir(PROJECT_ROOT)
    WAREHOUSE.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(WAREHOUSE))
    try:
        prepare(con)
    except DataQualityError as error:
        print(error)
        sys.exit(1)
    finally:
        con.close()
    print("Data quality OK.")


if __name__ == "__main__":
    clean()