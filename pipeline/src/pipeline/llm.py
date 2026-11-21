"""
The shared AI module: every AI feature goes through here, so no step is ever skipped.

    1. Query     query(sql)            runs one SELECT as ai_reader (read-only, 5 s, row limit)
    2. Generate  generate(...)         Gemini writes JSON from the query results only;
                                       if Gemini fails or is rate-limited, Groq writes instead
    3. Judge     judge(...)            Cohere checks every number and claim against the same
                                       query results: pass or fail, with a reason
    4. Decide    grounded(...)         pass -> keep it; fail -> regenerate once with the judge's
                                       reason; fail again (or judge unavailable) -> withhold

Every generate and judge call is logged in Neon (table llm_calls): prompt, output, verdict,
reason, provider, model, time taken, error.

Settings come from .env:
    AI_DATABASE_URL                 read-only role, for query()
    NEON_DATABASE_URL               owner role, only for writing the llm_calls log
    GOOGLE_GENERATIVE_AI_API_KEY    Gemini (GEMINI_API_KEY also works)
    GROQ_API_KEY                    fallback generator
    COHERE_API_KEY                  judge
    GEMINI_MODEL, GEMINI_BACKUP_MODEL, GROQ_MODEL, COHERE_MODEL   optional, to change models

Busy models: a 429/5xx answer is retried twice (after 2 s and 6 s); then the backup Gemini model;
then Groq. A Groq model that no longer exists is replaced by one Groq still offers.

Test it with:  python scripts/check_ai.py
"""

import json
import os
import time
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import psycopg
import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")

AI_URL = os.getenv("AI_DATABASE_URL")
OWNER_URL = os.getenv("NEON_DATABASE_URL")
GEMINI_KEY = os.getenv("GOOGLE_GENERATIVE_AI_API_KEY") or os.getenv("GEMINI_API_KEY")
GROQ_KEY = os.getenv("GROQ_API_KEY")
COHERE_KEY = os.getenv("COHERE_API_KEY")

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
GEMINI_BACKUP_MODEL = os.getenv("GEMINI_BACKUP_MODEL", "gemini-flash-lite-latest")  # when the main one is busy
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
# If GROQ_MODEL is gone, the first of these that Groq still offers is used instead
GROQ_PREFERRED = ["openai/gpt-oss-120b", "llama-3.3-70b-versatile", "openai/gpt-oss-20b",
                  "llama-3.1-8b-instant"]
COHERE_MODEL = os.getenv("COHERE_MODEL", "command-a-03-2025")

ROW_LIMIT = 200          # most rows a query may return to the AI
QUERY_TIMEOUT_S = 5      # most seconds a query may run
HTTP_TIMEOUT_S = 60      # most seconds to wait for a model
AI_SCHEMA = PROJECT_ROOT / "pipeline" / "sql" / "neon" / "ai_schema.sql"


class LLMError(Exception):
    """A model call failed (network, key, rate limit, bad JSON)."""


# ---------------------------------------------------------------- 1. Query

def _plain(v):
    """Make database values JSON-friendly (Decimal -> float, dates -> text)."""
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def query(sql, params=None, row_limit=ROW_LIMIT):
    """Run one SELECT as ai_reader. Read-only, 5-second limit, at most row_limit rows.
    Returns {"sql", "columns", "rows", "truncated"}: exactly what the model and the judge see."""
    if not AI_URL:
        raise RuntimeError("AI_DATABASE_URL is not set in .env")
    with psycopg.connect(AI_URL, connect_timeout=30) as con:
        with con.transaction():
            con.execute("SET TRANSACTION READ ONLY")
            con.execute(f"SET LOCAL statement_timeout = '{QUERY_TIMEOUT_S}s'")
            cur = con.execute(sql, params)
            columns = [d.name for d in cur.description]
            rows = cur.fetchmany(row_limit + 1)
    truncated = len(rows) > row_limit
    rows = [[_plain(v) for v in r] for r in rows[:row_limit]]
    return {"sql": " ".join(sql.split()), "columns": columns, "rows": rows, "truncated": truncated}


# ---------------------------------------------------------------- Log

_schema_ready = False


def _log(**row):
    """Write one row to llm_calls. Logging must never break the feature, so errors only print."""
    global _schema_ready
    if not OWNER_URL:
        print("  (llm log skipped: NEON_DATABASE_URL not set)")
        return
    try:
        with psycopg.connect(OWNER_URL, connect_timeout=30) as con:
            if not _schema_ready:
                con.execute(AI_SCHEMA.read_text())
                _schema_ready = True
            con.execute(
                """INSERT INTO llm_calls (run_id, purpose, step, attempt, provider, model, prompt,
                                          output, verdict, reason, latency_ms, error)
                   VALUES (%(run_id)s, %(purpose)s, %(step)s, %(attempt)s, %(provider)s, %(model)s,
                           %(prompt)s, %(output)s, %(verdict)s, %(reason)s, %(latency_ms)s, %(error)s)""",
                {"output": None, "verdict": None, "reason": None, "error": None, **row})
    except psycopg.Error as e:
        print(f"  (llm log failed: {str(e).splitlines()[0]})")


# ---------------------------------------------------------------- Schemas

def validate(obj, schema, path="output"):
    """A small JSON Schema check (type, required, properties, items, enum, minItems, maxItems).
    Raises LLMError with the first problem, so a malformed answer is never stored."""
    t = schema.get("type")
    types = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool,
             "number": (int, float)}
    if t and not isinstance(obj, types[t]):
        raise LLMError(f"{path} should be {t}")
    if "enum" in schema and obj not in schema["enum"]:
        raise LLMError(f"{path} should be one of {schema['enum']}")
    if t == "object":
        for key in schema.get("required", []):
            if key not in obj:
                raise LLMError(f"{path} is missing '{key}'")
        for key, sub in schema.get("properties", {}).items():
            if key in obj:
                validate(obj[key], sub, f"{path}.{key}")
    if t == "array":
        if len(obj) < schema.get("minItems", 0) or len(obj) > schema.get("maxItems", 10**9):
            raise LLMError(f"{path} has {len(obj)} items")
        for i, item in enumerate(obj):
            validate(item, schema.get("items", {}), f"{path}[{i}]")
    return obj


def _parse_json(text):
    text = text.strip()
    if text.startswith("```"):                       # some models wrap JSON in a code fence
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise LLMError(f"not valid JSON: {text[:200]}") from None


# ---------------------------------------------------------------- Providers

RETRY_CODES = {429, 500, 502, 503, 504}   # busy or rate-limited: worth a short wait and a retry
RETRY_WAITS = [2, 6]                       # seconds before the 2nd and 3rd try


def _post(url, headers, body):
    """POST JSON; retry twice on 'busy' answers (429/5xx) before giving up."""
    for wait in RETRY_WAITS + [None]:
        try:
            r = requests.post(url, headers=headers, json=body, timeout=HTTP_TIMEOUT_S)
        except requests.RequestException as e:
            if wait is None:
                raise LLMError(f"network: {e}") from None
            time.sleep(wait)
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code in RETRY_CODES and wait is not None:
            time.sleep(wait)
            continue
        raise LLMError(f"HTTP {r.status_code}: {' '.join(r.text.split())[:300]}")


def _gemini_once(model, system, prompt, schema):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {"x-goog-api-key": GEMINI_KEY}
    config = {"temperature": 0.2, "responseMimeType": "application/json"}
    body = {"systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {**config, "responseJsonSchema": schema}}
    try:
        data = _post(url, headers, body)
    except LLMError as e:
        if "HTTP 400" not in str(e) or "chema" not in str(e):
            raise
        body["generationConfig"] = config          # older API: schema stays in the prompt only
        data = _post(url, headers, body)
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise LLMError(f"empty Gemini answer: {json.dumps(data)[:300]}") from None


def _gemini(system, prompt, schema):
    """Main Gemini model; if it is busy or failing, the lighter backup model."""
    try:
        return _gemini_once(GEMINI_MODEL, system, prompt, schema)
    except LLMError as first:
        if not GEMINI_BACKUP_MODEL or GEMINI_BACKUP_MODEL == GEMINI_MODEL:
            raise
        try:
            return _gemini_once(GEMINI_BACKUP_MODEL, system, prompt, schema)
        except LLMError as second:
            raise LLMError(f"{GEMINI_MODEL}: {first} | {GEMINI_BACKUP_MODEL}: {second}") from None


_groq_model = None


def groq_model():
    """GROQ_MODEL if Groq still offers it, else the first preferred model it does offer."""
    global _groq_model
    if _groq_model:
        return _groq_model
    try:
        r = requests.get("https://api.groq.com/openai/v1/models",
                         headers={"Authorization": f"Bearer {GROQ_KEY}"}, timeout=HTTP_TIMEOUT_S)
        available = {m["id"] for m in r.json().get("data", [])} if r.status_code == 200 else set()
    except requests.RequestException:
        available = set()
    if not available or GROQ_MODEL in available:
        _groq_model = GROQ_MODEL
    else:
        _groq_model = next((m for m in GROQ_PREFERRED if m in available), sorted(available)[0])
        print(f"  (Groq no longer offers {GROQ_MODEL}; using {_groq_model}. "
              f"Set GROQ_MODEL={_groq_model} in .env to make this permanent.)")
    return _groq_model


def _groq(system, prompt, schema):
    data = _post("https://api.groq.com/openai/v1/chat/completions",
                 {"Authorization": f"Bearer {GROQ_KEY}"},
                 {"model": groq_model(), "temperature": 0.2,
                  "response_format": {"type": "json_object"},
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": prompt}]})
    return data["choices"][0]["message"]["content"]


def _cohere(system, prompt, schema):
    data = _post("https://api.cohere.com/v2/chat",
                 {"Authorization": f"Bearer {COHERE_KEY}"},
                 {"model": COHERE_MODEL, "temperature": 0,
                  "response_format": {"type": "json_object", "json_schema": schema},
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": prompt}]})
    return data["message"]["content"][0]["text"]


PROVIDERS = {"gemini": (_gemini, lambda: GEMINI_MODEL, lambda: GEMINI_KEY),
             "groq": (_groq, groq_model, lambda: GROQ_KEY),
             "cohere": (_cohere, lambda: COHERE_MODEL, lambda: COHERE_KEY)}


def call(provider, system, prompt, schema, *, run_id, purpose, step, attempt):
    """One logged model call that must return JSON matching schema."""
    fn, model, key = PROVIDERS[provider]
    if not key():
        raise LLMError(f"{provider} key is not set in .env")
    start = time.time()
    text, error = None, None
    try:
        text = fn(system, prompt, schema)
        return validate(_parse_json(text), schema)
    except (LLMError, KeyError, IndexError) as e:
        error = str(e)
        raise LLMError(error) from None
    finally:
        out = _parse_json_or_none(text)
        _log(run_id=run_id, purpose=purpose, step=step, attempt=attempt, provider=provider,
             model=model(), prompt=f"[system]\n{system}\n\n[user]\n{prompt}", output=text,
             verdict=out.get("verdict") if step == "judge" and isinstance(out, dict) else None,
             reason=out.get("reason") if step == "judge" and isinstance(out, dict) else None,
             latency_ms=int((time.time() - start) * 1000), error=error)


def _parse_json_or_none(text):
    try:
        return json.loads(text) if text else None
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------- 2. Generate

GENERATE_RULES = """You are a careful advertising analyst writing for a busy manager.
Rules:
- Use ONLY the numbers and facts in DATA. Never use outside knowledge about these advertisers.
- Every number you write must appear in DATA. You may round it and add thousands separators, but never
  calculate a new number (no sums, differences or ratios of your own).
- Percentages: a column named ..._pct is already a percentage (23.0 -> 23%), never multiply it by 100.
  Only a fraction between 0 and 1 becomes a percentage (0.0723 -> 7.23%).
- If DATA does not support a claim, leave the claim out. Never guess causes; say "the data shows" only
  what DATA shows.
- Plain language, short sentences.
- Answer with JSON only, matching SCHEMA exactly."""


def _data_block(data):
    return json.dumps(data, ensure_ascii=False, default=str)


def generate(task, data, schema, *, run_id, purpose, attempt=1, feedback=None):
    """Gemini first; Groq if Gemini fails. Returns (output, provider)."""
    prompt = (f"TASK:\n{task}\n\nDATA (query results):\n{_data_block(data)}\n\n"
              f"SCHEMA:\n{json.dumps(schema)}")
    if feedback:
        prompt += (f"\n\nA fact checker rejected your previous answer: {feedback}\n"
                   "Write a new answer that fixes this. Use only numbers that appear in DATA.")
    errors = []
    for provider in ("gemini", "groq"):
        try:
            out = call(provider, GENERATE_RULES, prompt, schema,
                       run_id=run_id, purpose=purpose, step="generate", attempt=attempt)
            return out, provider
        except LLMError as e:
            errors.append(f"{provider}: {e}")
    raise LLMError(" | ".join(errors))


# ---------------------------------------------------------------- 3. Judge

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["pass", "fail"]},
        "reason": {"type": "string"},
        "problems": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["verdict", "reason", "problems"],
}

JUDGE_RULES = """You are a strict fact checker for an advertising dashboard.
You get DATA (database query results) and an ANSWER written from it. Check the ANSWER claim by claim.
Return "fail" if ANY of these is true:
- a number in the ANSWER does not appear in DATA (rounding a DATA value is allowed);
- a percentage in the ANSWER is not the DATA value: a column named ..._pct is already a percentage
  (23.0 -> 23%; 2,300% is WRONG); only a fraction between 0 and 1 may be multiplied by 100 (0.0723 -> 7.23%);
- a share or rate (CTR, win rate, share of the bid) in the ANSWER is above 100%;
- a comparison, ranking, direction (up/down, highest/lowest) or trend is not supported by DATA;
- the ANSWER names an advertiser, day, hour, exchange or segment that is not in DATA;
- the ANSWER states a cause that DATA does not show.
Otherwise return "pass".
"reason": one sentence. "problems": each wrong claim, quoted, with what DATA actually says ([] when pass).
Answer with JSON only: {"verdict": "pass"|"fail", "reason": "...", "problems": [...]}"""


def judge(task, data, output, *, run_id, purpose, attempt=1):
    """Cohere checks output against data. Returns {"verdict", "reason", "problems"}."""
    prompt = (f"TASK the answer was written for:\n{task}\n\nDATA:\n{_data_block(data)}\n\n"
              f"ANSWER:\n{json.dumps(output, ensure_ascii=False)}")
    return call("cohere", JUDGE_RULES, prompt, JUDGE_SCHEMA,
                run_id=run_id, purpose=purpose, step="judge", attempt=attempt)


# ---------------------------------------------------------------- 4. Show or withhold

def grounded(task, data, schema, *, purpose):
    """Generate, judge, regenerate once if needed. Never returns an unjudged answer.

    Returns a dict:
        status    "pass" (show it) or "withheld" (don't)
        output    the answer (None when withheld)
        rejected  the last answer the judge failed (kept for the log and the blog post)
        verdict   the judge's last verdict
        note      why it was withheld
        provider  who wrote the answer
        run_id    to find every call in llm_calls
        sql       the queries behind it, to show next to the answer
    """
    run_id = uuid.uuid4()
    sql = [d["sql"] for d in data.values() if isinstance(d, dict) and "sql" in d]
    result = {"status": "withheld", "output": None, "rejected": None, "verdict": None,
              "note": None, "provider": None, "run_id": str(run_id), "sql": sql}
    feedback = None
    for attempt in (1, 2):
        try:
            output, provider = generate(task, data, schema, run_id=run_id, purpose=purpose,
                                        attempt=attempt, feedback=feedback)
        except LLMError as e:
            result["note"] = f"no model could write an answer: {e}"
            return result
        try:
            verdict = judge(task, data, output, run_id=run_id, purpose=purpose, attempt=attempt)
        except LLMError as e:
            result.update(rejected=output, provider=provider,
                          note=f"withheld: the judge was unavailable ({e})")
            return result
        result.update(verdict=verdict, provider=provider)
        if verdict["verdict"] == "pass":
            result.update(status="pass", output=output, note=None)
            return result
        result["rejected"] = output
        feedback = verdict["reason"] + (" Problems: " + "; ".join(verdict["problems"])
                                        if verdict["problems"] else "")
    result["note"] = f"withheld after 2 attempts: {verdict['reason']}"
    return result