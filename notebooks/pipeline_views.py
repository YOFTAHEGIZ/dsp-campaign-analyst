"""
Views for the analysis notebooks, built from the pipeline's files.

The notebooks read the views raw_<log> (every column as text, one row per log line) and
typed_<log> (numbers, timestamps and real NULLs) for log = bid, imp, clk, conv.

They used to come from data/processed/ipinyou.duckdb, the database the loading notebook built.
When that file is gone (for example deleted to free disk space), create_views() builds the same
views in memory from the pipeline's hourly Parquet files in data/interim/<log>/.
Nothing is written to disk.

Bids: the full bid rows of all advertisers come from data/interim/bid_parquet (the loading
notebook's files) if they are still there; otherwise from the pipeline's data/interim/bid/, which
holds only the advertisers in BID_ADVERTISER_IDS (1458 on a laptop with little disk).
"""

from pathlib import Path

LOGS = ["bid", "imp", "clk", "conv"]
INT_COLS = ["log_type", "region", "city", "ad_exchange", "ad_slot_width", "ad_slot_height",
            "ad_slot_visibility", "ad_slot_format", "ad_slot_floor_price",
            "bidding_price", "paying_price", "advertiser_id"]


def _listing(files):
    return "[" + ", ".join(f"'{Path(f).as_posix()}'" for f in files) + "]"


def _typed(con, log):
    columns = [row[0] for row in con.execute(f"DESCRIBE raw_{log}").fetchall() if row[0] != "filename"]

    def expr(c):
        text = f"""CASE WHEN lower("{c}") IN ('', 'null') THEN NULL ELSE "{c}" END"""
        if c == "timestamp":
            return f"TRY_STRPTIME({text}, '%Y%m%d%H%M%S%g')"
        return f"TRY_CAST({text} AS BIGINT)" if c in INT_COLS else text

    con.execute(f"CREATE OR REPLACE TEMP VIEW typed_{log} AS SELECT "
                + ", ".join(f'{expr(c)} AS "{c}"' for c in columns)
                + f", regexp_extract(filename, '([0-9]{{8}})\\.txt$', 1) AS log_date FROM raw_{log}")


def create_views(con, project_root):
    """Create raw_* and typed_* for the 4 logs. Returns a one-line description of the data used."""
    interim = Path(project_root) / "data" / "interim"
    notes = []
    for log in LOGS:
        files = sorted((interim / log).glob(f"{log}_*_*.parquet"))
        legacy = []
        if log == "bid":
            old = interim / "bid_parquet"
            legacy = sorted(old.glob("bid_*.parquet")) + sorted(
                p for p in old.glob("bid_*/part_*.parquet") if not p.parent.name.endswith(".partial"))
        if legacy:
            # the loading notebook's bid files: all advertisers, and they already have "filename"
            con.execute(f"CREATE OR REPLACE TEMP VIEW raw_bid AS SELECT * FROM read_parquet("
                        f"{_listing(legacy)}, union_by_name = true)")
            notes.append("bids: all advertisers (data/interim/bid_parquet)")
        elif files:
            # the pipeline's hourly files; "filename" like the raw file, e.g. imp.20130606.txt
            con.execute(f"CREATE OR REPLACE TEMP VIEW raw_{log} AS "
                        f"SELECT * EXCLUDE (source_file), regexp_replace(source_file, '\\.bz2$', '') AS filename "
                        f"FROM read_parquet({_listing(files)}, union_by_name = true)")
            if log == "bid":
                advertisers = [str(r[0]) for r in con.execute(
                    "SELECT DISTINCT advertiser_id FROM raw_bid ORDER BY 1").fetchall()]
                notes.append(f"bids: advertisers {', '.join(advertisers)} only (data/interim/bid)")
        else:
            raise FileNotFoundError(
                f"No {log} files in {interim / log}. Run the pipeline first: python pipeline/src/pipeline/ingest.py")
        _typed(con, log)
    return "the pipeline's hourly Parquet files (data/interim), in memory; " + "; ".join(notes)