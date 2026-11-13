"""
Scheduler: runs the hourly pipeline on a timer, forever.

    python pipeline/src/pipeline/scheduler.py            # a tick every TICK_SECONDS
    python pipeline/src/pipeline/scheduler.py --once     # one tick, then stop

Every tick:
  1. ingest.py     picks up raw files that are new or changed (finished days are skipped in
                   a second, so this is cheap)
  2. tick.py       processes the next HOURS_PER_TICK hour(s) and moves the watermark

Settings (in .env or in compose.yaml):
  TICK_SECONDS     time between ticks. 3600 = one hour of data per real hour.
                   For a demo, 60 replays one hour of 2013 every minute (the week in ~3 hours).
  HOURS_PER_TICK   hours of data per tick (default 1)

A failed tick is logged and the scheduler keeps going: the watermark did not move, so the next
tick tries the same hour again. Ticks never overlap: the next one starts only after the
previous one has finished.
"""

import argparse
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")

TICK_SECONDS = int(os.getenv("TICK_SECONDS", "3600"))
HOURS_PER_TICK = int(os.getenv("HOURS_PER_TICK", "1"))

stopping = False


def stop(signum, frame):
    """Docker sends SIGTERM on `docker compose stop`: finish the current tick, then exit."""
    global stopping
    stopping = True
    print("Stop requested: the scheduler stops after the current tick.", flush=True)


def log(message):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}", flush=True)


def run_step(script, *options):
    result = subprocess.run([sys.executable, str(HERE / script), *options], cwd=PROJECT_ROOT)
    return result.returncode == 0


def one_tick():
    if not run_step("ingest.py"):
        log("ingest failed; trying again next tick")
        return False
    if not run_step("tick.py", "--hours", str(HOURS_PER_TICK)):
        log("tick failed; the watermark did not move, the same hour is tried again next tick")
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description="Run the hourly pipeline on a timer")
    parser.add_argument("--once", action="store_true", help="run one tick and stop")
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    if args.once:
        sys.exit(0 if one_tick() else 1)

    log(f"Scheduler started: a tick every {TICK_SECONDS}s, {HOURS_PER_TICK} hour(s) of data per tick")
    while not stopping:
        started = time.time()
        log("tick")
        one_tick()
        # wait until the next tick is due, checking every second whether we should stop
        while not stopping and time.time() - started < TICK_SECONDS:
            time.sleep(1)
    log("Scheduler stopped")


if __name__ == "__main__":
    main()