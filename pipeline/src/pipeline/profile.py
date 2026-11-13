"""
Profile: describe every column of the raw logs.

    python pipeline/src/pipeline/profile.py

Reads the Parquet files made by ingest.py (data/interim/<log>/), where every column is still
text, exactly as in the raw logs. For each column of each log it measures:

    missing_pct    share of rows that are empty or the text 'null'
    distinct       number of different values (approximate for big logs, within ~2%)
    top_value      the most common value, and top_pct, its share of rows
    min / max      for columns that hold numbers

Saves reports/column_profile.csv and prints a short table. docs/data_decisions.md explains
which columns were kept or dropped, based on this profile.
"""

import csv
import os
from pathlib import Path

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[3]
REPORT = Path("reports/column_profile.csv")
LOGS = ["imp", "clk", "conv", "bid"]


def profile_log(con, log):
    files = f"data/interim/{log}/{log}_*.parquet"
    columns = [
        row[0] for row in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{files}')").fetchall()
        if row[0] != "source_file"
    ]
    rows = con.execute(f"SELECT COUNT(*) FROM read_parquet('{files}')").fetchall()[0][0]

    results = []
    for column in columns:
        c = f'"{column}"'
        missing, distinct, low, high = con.execute(f"""
            SELECT
                COUNT(*) FILTER (WHERE {c} IS NULL OR {c} IN ('', 'null')),
                APPROX_COUNT_DISTINCT({c}),
                MIN(TRY_CAST({c} AS DOUBLE)),
                MAX(TRY_CAST({c} AS DOUBLE))
            FROM read_parquet('{files}')
        """).fetchall()[0]
        top_value, top_count = con.execute(f"""
            SELECT {c}, COUNT(*) FROM read_parquet('{files}')
            GROUP BY 1 ORDER BY 2 DESC LIMIT 1
        """).fetchall()[0]
        results.append({
            "log": log,
            "column": column,
            "rows": rows,
            "missing_pct": round(100 * missing / rows, 2) if rows else 0,
            "distinct": distinct,
            "top_value": (top_value or "")[:40],
            "top_pct": round(100 * top_count / rows, 2) if rows else 0,
            "min": low,
            "max": high,
        })
    return results


def profile():
    os.chdir(PROJECT_ROOT)
    con = duckdb.connect()
    results = []
    for log in LOGS:
        if not list(Path(f"data/interim/{log}").glob(f"{log}_*.parquet")):
            print(f"{log}: no files, skipped (run ingest.py first)")
            continue
        print(f"Profiling {log} ...", flush=True)
        results += profile_log(con, log)

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with REPORT.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)

    print(f"\n{'log':<5}{'column':<22}{'missing %':>10}{'distinct':>12}  top value (share)")
    print("-" * 80)
    for r in results:
        print(f"{r['log']:<5}{r['column']:<22}{r['missing_pct']:>10}{r['distinct']:>12,}  "
              f"{r['top_value'][:20]} ({r['top_pct']}%)")
    print(f"\nSaved {REPORT}")


if __name__ == "__main__":
    profile()