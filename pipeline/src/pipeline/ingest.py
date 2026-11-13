"""
Ingest: raw iPinYou logs -> Parquet files, one file per log per HOUR.

    python pipeline/src/pipeline/ingest.py            # all logs, all days
    python pipeline/src/pipeline/ingest.py --logs imp clk conv
    python pipeline/src/pipeline/ingest.py --force    # convert again, even if done

What it does:
* Finds every raw file named bid/imp/clk/conv.YYYYMMDD.txt(.bz2) under RAW_DIR (sub-folders too).
* Reads the .bz2 files as a stream, a few MB at a time, so nothing is decompressed to disk.
* Splits every day into hours: data/interim/<log>/<log>_<file day>_<YYYYMMDDHH>.parquet,
  where YYYYMMDDHH is the hour of the event's timestamp. The hourly pipeline (tick.py) picks up
  one hour at a time; the batch pipeline (run.py) simply reads all hours.
* Advertisers: ADVERTISER_IDS for impressions, clicks and conversions, and BID_ADVERTISER_IDS
  for the bid logs. Both default to all (every advertiser in the logs). The bid logs are by far
  the biggest, so on a laptop with little free disk set BID_ADVERTISER_IDS=1458 in .env.
* Keeps every column as text, exactly as in the log. Types are set later in the staging SQL,
  so no row is lost here because of one bad value.
* For the bid logs it also saves data/interim/bid_summary/: bid counts for ALL advertisers
  (per advertiser, date, hour, exchange and floor price), whatever BID_ADVERTISER_IDS says.
  That small table is all the dashboard's auction numbers need.

Safe to run again (idempotent):
* When a day is finished, a small "done" note is saved in data/interim/<log>/_done/<day>.json with
  the size of the raw file and the advertisers kept. A day with a matching note is skipped.
* If the raw file changed size (re-downloaded, or more rows were added) or the advertisers in .env
  changed, that day's hourly files are deleted and the day is converted again.
* Files are written as .part first and renamed at the end, and the note is written last,
  so a crash never leaves a half day that looks finished.
* Day files from the earlier version (<log>_<YYYYMMDD>.parquet) are split into hours once,
  without reading the raw files again.
"""

import argparse
import bz2
import json
import os
import re
import time
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pcsv
import pyarrow.parquet as pq
from dotenv import load_dotenv


# Find the project root directory and make relative paths work from there
PROJECT_ROOT = Path(__file__).resolve().parents[3]
os.chdir(PROJECT_ROOT)
load_dotenv(PROJECT_ROOT / ".env")

RAW_DIR = Path(os.getenv("RAW_DIR", "data"))
INTERIM_DIR = Path("data/interim")


def id_list(text):
    """'1458,2259' -> ['1458', '2259'].  'all' -> [] which means: keep every advertiser."""
    if text.strip().lower() == "all":
        return []
    return sorted(a.strip() for a in text.split(",") if a.strip())


ADVERTISER_IDS = id_list(os.getenv("ADVERTISER_IDS", "all"))
BID_ADVERTISER_IDS = id_list(os.getenv("BID_ADVERTISER_IDS", "all"))


def describe(ids):
    return ", ".join(ids) if ids else "all"


def advertisers_for(log):
    return BID_ADVERTISER_IDS if log == "bid" else ADVERTISER_IDS


# Column names from the dataset guide (the files have no header row)
EVENT_COLUMNS = [
    "bid_id", "timestamp", "log_type", "ipinyou_id", "user_agent", "ip",
    "region", "city", "ad_exchange", "domain", "url", "anonymous_url_id",
    "ad_slot_id", "ad_slot_width", "ad_slot_height", "ad_slot_visibility",
    "ad_slot_format", "ad_slot_floor_price", "creative_id", "bidding_price",
    "paying_price", "key_page_url", "advertiser_id", "user_tags",
]
# Bid logs have no log type, paying price or key page URL (21 columns)
BID_COLUMNS = [c for c in EVENT_COLUMNS if c not in ("log_type", "paying_price", "key_page_url")]
COLUMNS = {"bid": BID_COLUMNS, "imp": EVENT_COLUMNS, "clk": EVENT_COLUMNS, "conv": EVENT_COLUMNS}

FILE_NAME = re.compile(r"^(bid|imp|clk|conv)\.(\d{8})\.txt(\.bz2)?$")
SUMMARY_KEYS = ["advertiser_id", "bid_date", "hour", "ad_exchange", "floor_price"]


def find_raw_files():
    """Return {(log, day): path} for every raw log file under RAW_DIR.
    Folders whose name starts with 'test' are skipped (we only use the training days).
    If a day exists both as .txt and .txt.bz2, the .bz2 file is used."""
    found = {}
    for path in sorted(RAW_DIR.rglob("*.txt*")):
        match = FILE_NAME.match(path.name)
        # only the folders inside RAW_DIR count (a parent folder of the project may be called "test...")
        inside = path.parent.relative_to(RAW_DIR).parts
        if not match or any(part.lower().startswith("test") for part in inside):
            continue
        key = (match.group(1), match.group(2))
        if key not in found or path.suffix == ".bz2":
            found[key] = path
    return found


def open_raw(path):
    return bz2.open(path, "rb") if path.suffix == ".bz2" else open(path, "rb")


# ---- Where things are saved ----------------------------------------------------

def log_dir(log):
    return INTERIM_DIR / ("bid_summary" if log == "bid_summary" else log)


def hour_file(log, day, hour):
    """data/interim/imp/imp_20130606_2013060614.parquet (file day 6 June, events of 14:00-15:00)"""
    return log_dir(log) / f"{log}_{day}_{hour}.parquet"


def day_files(log, day):
    """Every hourly file (and leftover .part file) made from one raw day file."""
    return list(log_dir(log).glob(f"{log}_{day}_*.parquet")) + \
        list(log_dir(log).glob(f"{log}_{day}_*.parquet.part"))


def done_note(log, day):
    return log_dir(log) / "_done" / f"{day}.json"


def expected_note(log, source):
    return {"source": source.name, "source_size": source.stat().st_size,
            "advertisers": describe(advertisers_for(log))}


def is_up_to_date(log, day, source):
    """True if this day was converted from the same raw file, for the same advertisers."""
    note = done_note(log, day)
    if not note.exists():
        return False
    saved = json.loads(note.read_text())
    return all(saved.get(k) == v for k, v in expected_note(log, source).items())


def write_done_note(log, day, source, rows_read, rows_kept, hours):
    note = done_note(log, day)
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(json.dumps(
        expected_note(log, source) | {"rows_read": rows_read, "rows_kept": rows_kept, "hours": hours},
        indent=2))


def remove_day(log, day):
    """Delete a day's hourly files (and its bid summary) before converting it again."""
    for path in day_files(log, day) + (day_files("bid_summary", day) if log == "bid" else []):
        path.unlink()
    done_note(log, day).unlink(missing_ok=True)


# ---- Converting one raw day file ---------------------------------------------------

def convert(log, day, source):
    """Stream one raw day file into hourly Parquet files. Returns (rows read, rows kept, hours).

    Tries the fast reader first. If some rows have a different number of columns
    (the real conversion logs have rows without the last column, user_tags),
    the file is read again line by line, which handles uneven rows.
    For bid logs, a small summary of ALL bids is saved too (see summarize_bids)."""
    log_dir(log).mkdir(parents=True, exist_ok=True)
    remove_day(log, day)

    try:
        output = read_fast(log, day, source)
    except pa.ArrowInvalid as error:
        if "columns" not in str(error):
            raise
        remove_day(log, day)
        output = read_line_by_line(log, day, source)

    output.finish()
    if log == "bid":
        save_bid_summary(day, output.bid_summary())
    hours = sorted(output.writers)
    write_done_note(log, day, source, output.rows_read, output.rows_kept, len(hours))
    return output.rows_read, output.rows_kept, hours


def parquet_schema(log):
    # The advertisers kept are saved inside each file too, for anyone reading it later
    return pa.schema(
        [(c, pa.string()) for c in COLUMNS[log]] + [("source_file", pa.string())],
        metadata={"advertisers": describe(advertisers_for(log))},
    )


def hour_keys(timestamps, day):
    """YYYYMMDDHH of each timestamp. A broken timestamp goes to hour 00 of the file's day
    (the staging checks then report it)."""
    hours = pc.utf8_slice_codeunits(timestamps, 0, 10)
    valid = pc.match_substring_regex(hours, r"^\d{10}$")
    return pc.if_else(valid, hours, pa.scalar(f"{day}00", pa.string()))


class Output:
    """Receives batches of raw rows (all advertisers) and writes them into one file per hour.
    Keeps only the wanted advertisers; for bid logs it also counts every bid for the summary."""

    def __init__(self, log, day, source):
        self.log, self.day, self.source = log, day, source
        self.keep = advertisers_for(log)
        self.keep_array = pa.array(self.keep, pa.string())
        self.schema = parquet_schema(log)
        self.writers = {}  # hour -> ParquetWriter (writing to a .part file)
        self.summaries = []
        self.rows_read = self.rows_kept = 0

    def add(self, batch):
        self.rows_read += batch.num_rows
        if self.log == "bid":
            self.summaries.append(summarize_bids(batch))
        if self.keep:
            batch = batch.filter(pc.is_in(batch.column("advertiser_id"), value_set=self.keep_array))
        if batch.num_rows == 0:
            return
        table = pa.Table.from_batches([batch]).append_column(
            "source_file", pa.array([self.source.name] * batch.num_rows, pa.string()))
        hours = hour_keys(table.column("timestamp"), self.day)
        for hour in pc.unique(hours).to_pylist():
            rows = table.filter(pc.equal(hours, hour)).replace_schema_metadata(self.schema.metadata)
            if hour not in self.writers:
                part = hour_file(self.log, self.day, hour).with_suffix(".parquet.part")
                self.writers[hour] = pq.ParquetWriter(part, self.schema, compression="zstd")
            self.writers[hour].write_table(rows)
        self.rows_kept += batch.num_rows

    def close(self):
        for writer in self.writers.values():
            writer.close()

    def finish(self):
        """All rows written: turn the .part files into real files."""
        for hour in self.writers:
            final = hour_file(self.log, self.day, hour)
            final.with_suffix(".parquet.part").replace(final)

    def bid_summary(self):
        if not self.summaries:
            return pa.table({c: pa.array([], pa.string()) for c in SUMMARY_KEYS}
                            | {"bids": pa.array([], pa.int64()), "sum_bidding_price": pa.array([], pa.int64())})
        return group_summary(pa.concat_tables(self.summaries))


def read_fast(log, day, source):
    """The fast reader: pyarrow reads the file in big blocks."""
    columns = COLUMNS[log]
    output = Output(log, day, source)
    try:
        with open_raw(source) as f:
            if f.peek(1):  # an empty file simply gives no hourly files
                reader = pcsv.open_csv(
                    f,
                    read_options=pcsv.ReadOptions(column_names=columns, block_size=16 << 20),
                    # tab separated; quotes inside user agents are just text
                    parse_options=pcsv.ParseOptions(delimiter="\t", quote_char=False),
                    convert_options=pcsv.ConvertOptions(
                        column_types={c: pa.string() for c in columns},
                        strings_can_be_null=False,
                    ),
                )
                for batch in reader:
                    output.add(batch)
    finally:
        output.close()
    return output


def read_line_by_line(log, day, source):
    """Slower reader for files whose rows do not all have the same number of columns.
    Short rows get 'null' for the missing columns at the end (like the log's own
    missing values); extra fields are joined into the last column. Nothing is dropped."""
    columns = COLUMNS[log]
    n = len(columns)
    output = Output(log, day, source)
    uneven = {}  # number of columns -> how many rows had it

    def send(rows):
        arrays = [pa.array([r[i] for r in rows], pa.string()) for i in range(n)]
        output.add(pa.RecordBatch.from_arrays(arrays, names=columns))

    try:
        with open_raw(source) as f:
            buffer = []
            for line in f:
                fields = line.rstrip(b"\r\n").decode("utf-8", errors="replace").split("\t")
                if len(fields) != n:
                    uneven[len(fields)] = uneven.get(len(fields), 0) + 1
                    if len(fields) < n:
                        fields += ["null"] * (n - len(fields))
                    else:
                        fields = fields[: n - 1] + ["\t".join(fields[n - 1:])]
                buffer.append(fields)
                if len(buffer) >= 100_000:
                    send(buffer)
                    buffer = []
            if buffer:
                send(buffer)
    finally:
        output.close()

    details = ", ".join(f"{count:,} rows with {cols} columns" for cols, count in sorted(uneven.items()))
    print(f"    uneven rows (expected {n} columns): {details}. Read line by line, nothing dropped.")
    return output


# ---- Bid summary ------------------------------------------------------------
# The bid logs are huge, so on a laptop we may keep the full rows for one advertiser only.
# But the dashboard's auction numbers (bids, win rate, average bid) only need COUNTS. So while
# reading each bid file, we count ALL bids of ALL advertisers per
#     advertiser, date, hour, ad exchange, floor price
# and save that small table, one file per hour, in data/interim/bid_summary/.

def summarize_bids(batch):
    """Bid counts and bid price sums for one batch of raw bid rows (all text)."""
    timestamp = batch.column("timestamp")
    price = batch.column("bidding_price")
    price = pc.if_else(pc.match_substring_regex(price, r"^\d+$"), price, pa.scalar(None, pa.string()))
    table = pa.table({
        "advertiser_id": batch.column("advertiser_id"),
        "bid_date": pc.utf8_slice_codeunits(timestamp, 0, 8),
        "hour": pc.utf8_slice_codeunits(timestamp, 8, 10),
        "ad_exchange": batch.column("ad_exchange"),
        "floor_price": batch.column("ad_slot_floor_price"),
        "bids": pa.array([1] * batch.num_rows, pa.int64()),
        "sum_bidding_price": pc.cast(price, pa.int64()),
    })
    return group_summary(table)


def group_summary(table):
    grouped = table.group_by(SUMMARY_KEYS).aggregate([("bids", "sum"), ("sum_bidding_price", "sum")])
    return grouped.rename_columns(
        [{"bids_sum": "bids", "sum_bidding_price_sum": "sum_bidding_price"}.get(c, c)
         for c in grouped.column_names])


def save_bid_summary(day, summary):
    """One summary file per hour, like the logs."""
    log_dir("bid_summary").mkdir(parents=True, exist_ok=True)
    hours = pc.binary_join_element_wise(summary.column("bid_date"), summary.column("hour"), "")
    hours = hour_keys(hours, day)
    for hour in pc.unique(hours).to_pylist():
        target = hour_file("bid_summary", day, hour)
        part = target.with_suffix(".parquet.part")
        pq.write_table(summary.filter(pc.equal(hours, hour)), part, compression="zstd")
        part.replace(target)


# ---- Day files from the earlier version --------------------------------------------

def split_old_day_file(log, day, source):
    """The earlier version saved one file per day (<log>_<day>.parquet). If it holds the right
    advertisers, split it into hourly files instead of reading the raw file again.
    Returns True if it did. The day file is deleted only after every hour file is written."""
    old = log_dir(log) / f"{log}_{day}.parquet"
    old_summary = log_dir("bid_summary") / f"bid_summary_{day}.parquet"
    if not old.exists():
        return False
    metadata = pq.read_schema(old).metadata or {}
    if metadata.get(b"advertisers", b"").decode() != describe(advertisers_for(log)) or \
            (log == "bid" and not old_summary.exists()):
        old.unlink()  # made for other advertisers (or no summary): convert from the raw file
        return False

    remove_day(log, day)
    table = pq.read_table(old).replace_schema_metadata(parquet_schema(log).metadata)
    hours = hour_keys(table.column("timestamp"), day)
    hour_list = pc.unique(hours).to_pylist()
    for hour in hour_list:
        target = hour_file(log, day, hour)
        part = target.with_suffix(".parquet.part")
        pq.write_table(table.filter(pc.equal(hours, hour)), part, compression="zstd")
        part.replace(target)
    if log == "bid":
        save_bid_summary(day, pq.read_table(old_summary))
        old_summary.unlink()
    write_done_note(log, day, source, None, table.num_rows, len(hour_list))
    old.unlink()
    return True


# ---- Run -------------------------------------------------------------------

def run(logs, force=False):
    files = find_raw_files()
    if not files:
        raise SystemExit(f"No raw files found under {RAW_DIR}/ (expected imp.20130606.txt.bz2 ...). "
                         "Set RAW_DIR in .env to the folder with the .bz2 files.")

    print(f"Raw folder: {RAW_DIR}")
    print(f"Advertisers kept: {describe(ADVERTISER_IDS)} (bids: {describe(BID_ADVERTISER_IDS)})")

    # Small logs first, bids last (they are by far the biggest)
    order = {"clk": 0, "conv": 1, "imp": 2, "bid": 3}
    for (log, day), source in sorted(files.items(), key=lambda kv: (order[kv[0][0]], kv[0][1])):
        if log not in logs:
            continue
        if is_up_to_date(log, day, source) and not force:
            print(f"  {log} {day}: already converted, skipped")
            continue
        start = time.time()
        if not force and split_old_day_file(log, day, source):
            print(f"  {log} {day}: day file split into hours ({time.time() - start:.0f}s)")
            continue
        rows_read, rows_kept, hours = convert(log, day, source)
        print(f"  {log} {day}: {rows_read:,} rows read, {rows_kept:,} kept in {len(hours)} hourly files "
              f"({time.time() - start:.0f}s)")

    # A short summary: how many hours and which advertisers each log has
    for log in ("bid", "imp", "clk", "conv"):
        files_ = sorted(log_dir(log).glob(f"{log}_*_*.parquet"))
        hours = sorted({p.stem.rsplit("_", 1)[1] for p in files_})
        advertisers = set()
        for p in files_:
            column = pq.read_table(p, columns=["advertiser_id"]).column("advertiser_id")
            advertisers.update(pc.unique(column).to_pylist())
        span = f" ({hours[0][:8]} {hours[0][8:]}h to {hours[-1][:8]} {hours[-1][8:]}h)" if hours else ""
        print(f"{log:>5}: {len(hours)} hours{span}"
              + (f", advertisers {', '.join(sorted(advertisers))}" if advertisers else ""))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert raw iPinYou logs to hourly Parquet files")
    parser.add_argument("--logs", nargs="+", default=["bid", "imp", "clk", "conv"],
                        choices=["bid", "imp", "clk", "conv"])
    parser.add_argument("--force", action="store_true", help="convert days that already have files")
    args = parser.parse_args()
    run(args.logs, args.force)