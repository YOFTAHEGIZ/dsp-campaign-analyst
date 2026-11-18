"""Check that the ai_reader role can read the dashboard tables and nothing else.

Run from the project root, with .venv active:
    python scripts/check_ai_reader.py

It connects with AI_DATABASE_URL from .env and tries 4 things. Expected:
    PASS  read daily_campaign        (allowed)
    PASS  delete is blocked          (SELECT only: permission denied)
    PASS  create table is blocked    (no CREATE on the schema)
    PASS  load_log is hidden         (not a dashboard table)
"""
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
URL = os.getenv("AI_DATABASE_URL")
if not URL:
    raise SystemExit("AI_DATABASE_URL is not set in .env")
if "ai_reader" not in URL:
    raise SystemExit("AI_DATABASE_URL does not use the ai_reader role: check the user name in the URL")

# What is actually being used (password masked), to spot copy-paste mistakes
from urllib.parse import urlsplit
_u = urlsplit(URL)
_pw = _u.password or ""
_env = Path(__file__).resolve().parents[1] / ".env"
_lines = [l for l in _env.read_text().splitlines() if l.strip().startswith("AI_DATABASE_URL")] if _env.exists() else []
print(f"user: {_u.username} | password: {len(_pw)} characters, starts '{_pw[:2]}', ends '{_pw[-2:]}'"
      f" | host: {_u.hostname}")
if len(_lines) != 1:
    print(f"WARNING: .env has {len(_lines)} AI_DATABASE_URL lines; keep exactly one")
if os.environ.get("AI_DATABASE_URL") and _lines and _lines[-1].split("=", 1)[1].strip() != URL:
    print("WARNING: AI_DATABASE_URL is also set in your Terminal and overrides .env: run  unset AI_DATABASE_URL")
if any(c in _pw for c in " \"'"):
    print("WARNING: the password contains a space or quote: remove it")


def attempt(sql):
    """Run one statement in its own transaction. Returns (worked, message)."""
    try:
        with con.transaction(force_rollback=True):  # never keep anything
            cur = con.execute(sql)
            row = cur.fetchone() if cur.description else None
            return True, f"{row[0]:,} rows" if row else "ran"
    except psycopg.Error as e:
        return False, str(e).splitlines()[0]


# First: can ai_reader log in at all? If not, nothing else can be tested.
try:
    con = psycopg.connect(URL, connect_timeout=30, autocommit=True)
except psycopg.OperationalError as e:
    msg = str(e).strip().splitlines()[-1]
    print(f"FAIL  log in as ai_reader       {msg}")
    if "password authentication failed" in msg:
        print("\nThe password in AI_DATABASE_URL does not match the role's password.\n"
              "Set a new one in the Neon SQL Editor (as neondb_owner):\n"
              "    ALTER ROLE ai_reader WITH PASSWORD 'your-new-password';\n"
              "then paste exactly the same password into AI_DATABASE_URL in .env.")
    raise SystemExit(1)
print("PASS  log in as ai_reader")

checks = [
    ("read daily_campaign", "SELECT count(*) FROM daily_campaign", True),
    ("delete is blocked", "DELETE FROM daily_campaign WHERE false", False),
    ("create table is blocked", "CREATE TABLE ai_test (x int)", False),
    ("load_log is hidden", "SELECT count(*) FROM load_log", False),
]

ok = True
for name, sql, should_work in checks:
    worked, msg = attempt(sql)
    passed = worked == should_work
    ok &= passed
    print(f"{'PASS' if passed else 'FAIL'}  {name:<24} {msg}")
con.close()

print("\nai_reader is safe to use." if ok else
      "\nSomething is wrong: run pipeline/sql/neon/ai_reader_role.sql again as neondb_owner.")